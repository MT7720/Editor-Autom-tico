import subprocess
import platform
import os
import re
import math
import glob
import tempfile
import shutil
import json
import logging
import time
import atexit
import threading
import random
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Callable, IO
from queue import Queue, Empty
from math import ceil

# --- Configuração ---
logger = logging.getLogger(__name__)

# --- Classes Auxiliares ---

class FFmpegProcessManager:
    """Gerencia processos FFmpeg em execução para garantir a limpeza na saída."""
    def __init__(self):
        self.active_processes: Dict[int, subprocess.Popen] = {}
        self.lock = threading.Lock()
        atexit.register(self.shutdown)

    def add(self, process: subprocess.Popen):
        with self.lock:
            self.active_processes[process.pid] = process
            logger.debug(f"Processo {process.pid} adicionado. Total: {len(self.active_processes)}")

    def remove(self, process: subprocess.Popen):
        with self.lock:
            if process.pid in self.active_processes:
                del self.active_processes[process.pid]
                logger.debug(f"Processo {process.pid} removido. Restantes: {len(self.active_processes)}")

    def terminate_all(self):
        with self.lock:
            if not self.active_processes: return
            logger.info(f"Encerrando {len(self.active_processes)} processo(s) FFmpeg ativo(s)...")
            processes_to_kill = list(self.active_processes.values())
        
        for process in processes_to_kill:
            try:
                if process.poll() is None:
                    logger.warning(f"Forçando o encerramento do processo {process.pid}...")
                    process.terminate()
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        logger.error(f"O processo {process.pid} não encerrou, matando.")
                        process.kill()
            except Exception as e: logger.error(f"Erro ao encerrar o processo {process.pid}: {e}")
        
        with self.lock: self.active_processes.clear()

    def shutdown(self):
        self.terminate_all()

process_manager = FFmpegProcessManager()

# --- Lógica Principal ---

def _stream_reader(stream: Optional[IO], line_queue: Queue):
    """Lê linhas de um stream e as coloca em uma fila."""
    if not stream: return
    try:
        for line in iter(lambda: stream.read(1024), b''):
            line_queue.put(line.decode('utf-8', errors='ignore'))
    except Exception as e:
        logger.warning(f"O leitor de stream encontrou um erro: {e}")
    finally:
        try:
            stream.close()
        except Exception:
            pass

def _execute_ffmpeg(cmd: List[str], duration: float, progress_callback: Callable[[float], None], cancel_event: threading.Event, log_prefix: str, progress_queue: Queue) -> bool:
    logger.info(f"[{log_prefix}] Executando FFmpeg: {' '.join(cmd)}")
    progress_queue.put(("status", f"[{log_prefix}] Iniciando processo FFmpeg...", "info"))
    
    cmd_with_progress = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    creation_flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    
    process = subprocess.Popen(cmd_with_progress, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)
    process_manager.add(process)
    
    output_queue = Queue()
    stdout_thread = threading.Thread(target=_stream_reader, args=(process.stdout, output_queue), daemon=True)
    stderr_thread = threading.Thread(target=_stream_reader, args=(process.stderr, output_queue), daemon=True)
    stdout_thread.start(); stderr_thread.start()

    full_output = ""
    last_reported_pct = 0.0

    while process.poll() is None:
        if cancel_event.is_set():
            logger.warning(f"[{log_prefix}] Evento de cancelamento ativado. Encerrando processo FFmpeg {process.pid}.")
            progress_queue.put(("status", f"[{log_prefix}] Recebido sinal de cancelamento. Encerrando...", "warning"))
            process.terminate(); break

        try:
            for line in output_queue.get(timeout=0.1).split('\n'):
                full_output += line + '\n'
                if "out_time_ms=" in line:
                    time_ms_str = line.split("=")[1].strip()
                    if time_ms_str.isdigit():
                        current_time_sec = int(time_ms_str) / 1_000_000
                        if duration > 0:
                            progress_pct = min(current_time_sec / duration, 1.0)
                            progress_callback(progress_pct)
                            if progress_pct - last_reported_pct >= 0.05:
                               progress_queue.put(("status", f"[{log_prefix}] {int(progress_pct*100)}% concluído...", "info"))
                               last_reported_pct = progress_pct
                else:
                    logger.debug(f"[{log_prefix}/ffmpeg] {line.strip()}")
        except Empty:
            continue

    process.wait(timeout=5)
    process_manager.remove(process)
    
    while not output_queue.empty():
        full_output += output_queue.get_nowait()

    if cancel_event.is_set():
        logger.warning(f"[{log_prefix}] Processo cancelado.")
        return False
        
    if process.returncode == 0:
        logger.info(f"[{log_prefix}] Comando FFmpeg concluído com sucesso.")
        progress_callback(1.0)
        return True
    else:
        logger.error(f"[{log_prefix}] FFmpeg falhou com o código {process.returncode}.")
        logger.error(f"[{log_prefix}] Log do FFmpeg:\n{full_output}")
        error_snippet = "\n".join(full_output.strip().split("\n")[-5:])
        progress_queue.put(("status", f"[{log_prefix}] ERRO no FFmpeg: {error_snippet}", "error"))
        return False


def _probe_media_properties(path: str, ffmpeg_path: str) -> Optional[Dict]:
    if not path or not os.path.isfile(path): return None
    
    ffprobe_exe = "ffprobe.exe" if platform.system() == "Windows" else "ffprobe"
    ffprobe_path = os.path.join(Path(ffmpeg_path).parent, ffprobe_exe)
    if not os.path.exists(ffprobe_path):
        logger.warning(f"ffprobe não encontrado em {ffprobe_path}")
        return None
        
    try:
        cmd = [ffprobe_path, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
        creation_flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15, creationflags=creation_flags, encoding='utf-8', errors='ignore')
        return json.loads(result.stdout)
    except Exception as e:
        logger.warning(f"Não foi possível obter propriedades de '{Path(path).name}': {e}")
        return None

def _parse_resolution(res_str: str) -> Tuple[int, int]:
    match = re.search(r'(\d+)\s*[xX]\s*(\d+)', res_str)
    return (int(match.group(1)), int(match.group(2))) if match else (1920, 1080)

def _get_codec_params(params: Dict, force_reencode=False) -> List[str]:
    video_codec = params.get('video_codec', 'Automático')
    available_encoders = params.get('available_encoders', [])
    
    if not force_reencode:
        logger.info("Resolução do vídeo e legendas permitem cópia direta. Usando '-c:v copy'.")
        return ["-c:v", "copy"]

    encoder = "libx264"
    codec_flags = ["-preset", "veryfast", "-crf", "23"]
    
    auto_select_gpu = video_codec == 'Automático' and any(e in available_encoders for e in ["h264_nvenc", "hevc_nvenc"])

    if auto_select_gpu or "NVENC" in video_codec:
        if "hevc_nvenc" in available_encoders and ("HEVC" in video_codec or auto_select_gpu):
            encoder, codec_flags = "hevc_nvenc", ["-preset", "p4", "-cq", "23"]
        elif "h264_nvenc" in available_encoders:
            encoder, codec_flags = "h264_nvenc", ["-preset", "p4", "-cq", "23"]
            
    logger.info(f"Re-codificação de vídeo necessária. Usando encoder: {encoder}")
    return ["-c:v", encoder, *codec_flags, "-pix_fmt", "yuv420p"]

def _build_subtitle_style_string(style_params: Dict) -> str:
    """
    Constrói uma string de estilo ASS a partir de um dicionário de parâmetros.
    Esta função foi corrigida para extrair apenas os valores relevantes e formatá-los
    corretamente, evitando a inclusão de estruturas de dados (como dicionários)
    na string final, o que causava o erro de parsing do FFmpeg.
    """
    def to_ass_color(hex_color: str) -> str:
        hex_color = hex_color.lstrip('#')
        return f"&H{hex_color[4:6]}{hex_color[2:4]}{hex_color[0:2]}".upper() if len(hex_color) == 6 else "&H00FFFFFF"

    font_name = Path(style_params.get('font_file')).stem if style_params.get('font_file') else 'Arial'
    
    # Constrói um dicionário limpo apenas com as chaves e valores esperados pelo estilo ASS.
    style_parts = {
        'FontName': font_name,
        'FontSize': style_params.get('fontsize', 28),
        'PrimaryColour': to_ass_color(style_params.get('text_color', '#FFFFFF')),
        'OutlineColour': to_ass_color(style_params.get('outline_color', '#000000')),
        'BorderStyle': 1,
        'Outline': 2,
        'Shadow': 1,
        'Bold': -1 if style_params.get('bold', True) else 0,
        'Italic': -1 if style_params.get('italic', False) else 0,
        'Alignment': style_params.get('position_map', {}).get(style_params.get('position'), 2),
        'MarginV': int(style_params.get('fontsize', 28) * 0.7)
    }
    # Retorna a string formatada corretamente.
    return ",".join(f"{k}={v}" for k, v in style_parts.items())

def process_entrypoint(params: Dict[str, Any], progress_queue: Queue, cancel_event: threading.Event):
    temp_dir = tempfile.mkdtemp(prefix="kyle-editor-")
    logger.info(f"Processamento iniciado. Dir temporário: {temp_dir}")
    progress_queue.put(("status", "Diretório temporário criado.", "info"))
    success = False
    try:
        if cancel_event.is_set(): raise InterruptedError("Cancelado antes de iniciar.")
        
        media_type = params.get('media_type')
        if media_type == 'batch':
            success = _run_batch_processing(params, progress_queue, cancel_event, temp_dir)
        elif media_type == 'image_folder':
            success = _run_slideshow_processing(params, progress_queue, cancel_event, temp_dir)
        else:
            success = _run_single_item_processing(params, progress_queue, cancel_event)
            
    except InterruptedError:
        logger.warning("Processamento interrompido pelo usuário.")
        success = False
    except Exception as e:
        logger.critical(f"Exceção não tratada na thread de processamento: {e}", exc_info=True)
        progress_queue.put(("status", f"Erro CRÍTICO: {e}", "error"))
    finally:
        try: shutil.rmtree(temp_dir)
        except Exception as e: logger.error(f"Falha ao limpar o diretório temporário {temp_dir}: {e}")
        
        cancelled = cancel_event.is_set()
        progress_queue.put(("finish", success and not cancelled))
        final_message = "Processo cancelado pelo usuário." if cancelled else ("Processo concluído com sucesso!" if success else "Processo falhou.")
        final_tag = "warning" if cancelled else ("success" if success else "error")
        progress_queue.put(("status", final_message, final_tag))
        logger.info(f"Processamento finalizado. Sucesso: {success}, Cancelado: {cancelled}")

def _run_single_item_processing(params: Dict[str, Any], progress_queue: Queue, cancel_event: threading.Event, progress_callback: Optional[Callable[[float], None]] = None) -> bool:
    if cancel_event.is_set(): return False
    
    video_path = params['media_path_single']
    narration_path = params.get('narration_file_single')
    music_path = params.get('music_file_single')
    subtitle_path = params.get('subtitle_file_single')
    output_path = os.path.join(params['output_folder'], params['output_filename_single'])

    video_props = _probe_media_properties(video_path, params['ffmpeg_path'])
    if not video_props:
        progress_queue.put(("status", "Erro: Não foi possível ler as propriedades do vídeo de entrada.", "error")); return False
    
    video_stream = next((s for s in video_props.get('streams', []) if s['codec_type'] == 'video'), None)
    if not video_stream:
        progress_queue.put(("status", "Erro: Nenhuma trilha de vídeo encontrada no arquivo de entrada.", "error")); return False
        
    source_w, source_h = video_stream.get('width'), video_stream.get('height')
    target_w, target_h = _parse_resolution(params['resolution'])
    
    narration_duration = 0
    if narration_path and os.path.isfile(narration_path):
        props = _probe_media_properties(narration_path, params['ffmpeg_path'])
        if props and 'format' in props and 'duration' in props['format']:
            narration_duration = float(props['format']['duration'])
            progress_queue.put(("status", f"Duração da narração detectada: {narration_duration:.2f}s", "info"))
        else:
            progress_queue.put(("status", f"Aviso: Não foi possível ler a duração da narração '{Path(narration_path).name}'", "warning"))

    final_duration = narration_duration or float(video_props.get('format', {}).get('duration', 0))
    if final_duration <= 0:
        progress_queue.put(("status", "Erro: Não foi possível determinar a duração final.", "error")); return False

    inputs, filter_complex_parts, map_args = [], [], []
    
    inputs.extend(["-i", video_path])
    video_input_idx = 0
    
    audio_input_count = 0
    narration_input_idx = -1
    if narration_path and os.path.isfile(narration_path):
        inputs.extend(["-i", narration_path])
        audio_input_count += 1
        narration_input_idx = audio_input_count
    
    music_input_idx = -1
    if music_path and os.path.isfile(music_path):
        music_props = _probe_media_properties(music_path, params['ffmpeg_path'])
        music_duration = float(music_props.get('format', {}).get('duration', 0)) if music_props else 0
        
        if 0 < music_duration < final_duration:
            logger.info(f"Música ({music_duration:.1f}s) é mais curta que a duração final ({final_duration:.1f}s). Ativando loop.")
            inputs.extend(["-stream_loop", "-1"])
        
        inputs.extend(["-i", music_path])
        audio_input_count += 1
        music_input_idx = audio_input_count

    audio_to_mix = []
    if narration_input_idx != -1:
        filter_complex_parts.append(f"[{narration_input_idx}:a]volume={params['narration_volume']}dB[narrated]")
        audio_to_mix.append("[narrated]")
    if music_input_idx != -1:
        filter_complex_parts.append(f"[{music_input_idx}:a]volume={params['music_volume']}dB[music]")
        audio_to_mix.append("[music]")

    if len(audio_to_mix) > 1:
        filter_complex_parts.append(f"{''.join(audio_to_mix)}amix=inputs={len(audio_to_mix)}:duration=first:dropout_transition=3[aout]")
        map_args.extend(["-map", "[aout]"])
    elif len(audio_to_mix) == 1:
        map_args.extend(["-map", f"[{audio_input_count}:a]"])
    
    video_filters = []
    force_reencode = not (source_w == target_w and source_h == target_h)
    if force_reencode:
        video_filters.append(f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")

    if subtitle_path and os.path.isfile(subtitle_path):
        style_str = _build_subtitle_style_string(params['subtitle_style'])
        escaped_sub_path = str(Path(subtitle_path)).replace('\\', '/').replace(':', '\\:')
        video_filters.append(f"subtitles='{escaped_sub_path}':force_style='{style_str}'")
        force_reencode = True
    
    if video_filters:
        filter_complex_parts.insert(0, f"[{video_input_idx}:v]{','.join(video_filters)}[vout]")
        map_args.extend(["-map", "[vout]"])
    else:
        map_args.extend(["-map", f"{video_input_idx}:v"])

    cmd = [params['ffmpeg_path'], "-y", *inputs]
    if filter_complex_parts: cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
    cmd.extend(map_args)
    cmd.extend(_get_codec_params(params, force_reencode=force_reencode))
    if audio_to_mix: cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd.extend(["-t", str(final_duration), "-shortest", output_path])
    
    callback = progress_callback if progress_callback is not None else (lambda p: progress_queue.put(("progress", p)))
    return _execute_ffmpeg(cmd, final_duration, callback, cancel_event, "SinglePass", progress_queue)


def _run_slideshow_processing(params: Dict[str, Any], progress_queue: Queue, cancel_event: threading.Event, temp_dir: str) -> bool:
    if cancel_event.is_set(): return False
    
    narration_path = params.get('narration_file_single')
    if not narration_path or not os.path.isfile(narration_path):
        progress_queue.put(("status", "Erro: Arquivo de narração é obrigatório para slideshow.", "error")); return False
    
    progress_queue.put(("status", f"Analisando duração de: {Path(narration_path).name}", "info"))
    narration_props = _probe_media_properties(narration_path, params['ffmpeg_path'])
    if not narration_props or 'format' not in narration_props or 'duration' not in narration_props['format']:
        progress_queue.put(("status", "Erro CRÍTICO: Não foi possível ler a duração da narração.", "error")); return False
    narration_duration = float(narration_props['format']['duration'])

    img_folder = params.get('media_path_single')
    supported_ext = ('.png', '.jpg', '.jpeg', '.bmp', '.webp');
    images = sorted([os.path.join(img_folder, f) for f in os.listdir(img_folder) if f.lower().endswith(supported_ext)])
    if not images:
        progress_queue.put(("status", f"Erro: Nenhuma imagem encontrada em {img_folder}.", "error")); return False

    progress_queue.put(("status", "[Slideshow] Etapa 1: Gerando vídeo a partir das imagens...", "info"))
    
    img_duration = params.get('image_duration', 5)
    num_images_needed = ceil(narration_duration / img_duration) if img_duration > 0 else len(images)
    images_to_use = (images * (num_images_needed // len(images) + 1))[:num_images_needed]
    if not images_to_use:
        progress_queue.put(("status", "Erro: Nenhuma imagem para usar no slideshow.", "error")); return False

    concat_file_path = os.path.join(temp_dir, "imagelist.txt")
    try:
        with open(concat_file_path, 'w', encoding='utf-8') as f:
            for img_path in images_to_use:
                f.write(f"file '{Path(img_path).as_posix()}'\n")
                f.write(f"duration {img_duration}\n")
        
        with open(concat_file_path, 'a', encoding='utf-8') as f:
            f.write(f"file '{Path(images_to_use[-1]).as_posix()}'\n")
    except Exception as e:
        logger.error(f"Erro ao escrever o arquivo de concatenação: {e}", exc_info=True)
        progress_queue.put(("status", f"Erro CRÍTICO ao preparar o slideshow: {e}", "error")); return False

    base_video_path = os.path.join(temp_dir, "slideshow_video.mp4")
    w, h = _parse_resolution(params['resolution'])
    
    video_filters = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    
    cmd_video = [
        params['ffmpeg_path'], "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file_path,
        "-vf", video_filters,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-t", str(narration_duration),
        base_video_path
    ]
    
    progress_queue.put(("status", "[SlideshowGen] Iniciando processo FFmpeg...", "info"))
    if not _execute_ffmpeg(cmd_video, narration_duration, lambda p: progress_queue.put(("progress", p * 0.8)), cancel_event, "SlideshowGen", progress_queue):
        return False
    if cancel_event.is_set(): return False
    
    progress_queue.put(("status", "[Slideshow] Etapa 2: Combinando áudio(s) e legendas...", "info"))
    
    slideshow_params = {**params, 'media_path_single': base_video_path, 'narration_file_single': narration_path}
    
    def final_progress_callback(p: float):
        progress_queue.put(("progress", 0.8 + p * 0.2))

    return _run_single_item_processing(slideshow_params, progress_queue, cancel_event, progress_callback=final_progress_callback)


def _run_batch_processing(params: Dict[str, Any], progress_queue: Queue, cancel_event: threading.Event, temp_dir: str) -> bool:
    if cancel_event.is_set(): return False
    audio_folder = params.get('batch_audio_folder')
    video_parent_folder = params.get('batch_video_folder')
    srt_folder = params.get('batch_srt_folder')
    
    if not audio_folder or not os.path.isdir(audio_folder):
        progress_queue.put(("status", "Erro: Pasta de áudios do lote inválida.", "error")); return False
    if not video_parent_folder or not os.path.isdir(video_parent_folder):
        progress_queue.put(("status", "Erro: Pasta de vídeos do lote inválida.", "error")); return False

    audio_files = sorted([f for f in os.listdir(audio_folder) if os.path.isfile(os.path.join(audio_folder, f))])
    if not audio_files:
        progress_queue.put(("status", "Erro: Nenhum arquivo de áudio encontrado na pasta de lote.", "error")); return False
        
    total_files = len(audio_files)
    for i, audio_filename in enumerate(audio_files):
        if cancel_event.is_set(): return False
        
        progress_queue.put(("batch_progress", (i) / total_files))
        log_prefix = f"Lote {i+1}/{total_files}"
        progress_queue.put(("status", f"--- Iniciando {log_prefix}: {audio_filename} ---", "info"))
        
        lang_code_match = re.search(r'_(?P<lang>[a-z]{2}(_[A-Z]{2})?)\.', audio_filename)
        lang_code = lang_code_match.group('lang') if lang_code_match else 'default'
        
        video_lang_folder = os.path.join(video_parent_folder, lang_code)
        if not os.path.isdir(video_lang_folder):
            video_lang_folder = video_parent_folder
        
        available_videos = sorted([os.path.join(video_lang_folder, f) for f in os.listdir(video_lang_folder) if f.lower().endswith(('.mp4', '.mov', '.mkv'))])
        if not available_videos:
            progress_queue.put(("status", f"[{log_prefix}] Aviso: Nenhum vídeo encontrado em '{video_lang_folder}'. Pulando.", "warning")); continue

        subtitle_file = None
        if srt_folder and os.path.isdir(srt_folder):
            potential_srt = os.path.join(srt_folder, f"{Path(audio_filename).stem}.srt")
            if os.path.isfile(potential_srt):
                subtitle_file = potential_srt

        item_params = {**params,
            'media_path_single': random.choice(available_videos),
            'narration_file_single': os.path.join(audio_folder, audio_filename),
            'subtitle_file_single': subtitle_file,
            'music_file_single': None,
            'output_filename_single': f"video_final_{Path(audio_filename).stem}.mp4"
        }
        
        item_success = _run_single_item_processing(item_params, progress_queue, cancel_event)
        
        if not item_success and not cancel_event.is_set():
            progress_queue.put(("status", f"[{log_prefix}] Falha ao processar o item. Continuando...", "error"))

    progress_queue.put(("batch_progress", 1.0))
    return True
