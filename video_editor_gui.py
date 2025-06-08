import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
from ttkbootstrap.dialogs import Messagebox
import tkinter as tk
import tkinter.filedialog
import tkinter.colorchooser
import os
import subprocess
import threading
import platform
import queue
import re
import datetime
import json
import logging
import logging.handlers
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Dict, Any, Optional
from tkinter import font as tkFont
from pathlib import Path

try:
    import video_processing_logic
except ImportError:
    # Isso será tratado de forma elegante no aplicativo
    video_processing_logic = None

# --- Constantes ---
APP_NAME = "Kyle Video Editor v4.9"
DEFAULT_GEOMETRY = "1200x850"
CONFIG_FILE = "video_editor_config.json"
SUPPORTED_NARRATION_FT = [("Arquivos de Áudio", "*.mp3 *.wav *.aac *.ogg *.flac"), ("Todos os arquivos", "*.*")]
SUPPORTED_MUSIC_FT = SUPPORTED_NARRATION_FT
SUPPORTED_SUBTITLE_FT = [("Arquivos de Legenda SRT", "*.srt"), ("Todos os arquivos", "*.*")]
SUPPORTED_VIDEO_FT = [("Arquivos de Vídeo", "*.mp4 *.mov *.avi *.mkv"), ("Todos os arquivos", "*.*")]
SUPPORTED_IMAGE_FT = [("Arquivos de Imagem", "*.jpg *.jpeg *.png *.bmp *.webp"), ("Todos os arquivos", "*.*")]
SUPPORTED_FONT_FT = [("Arquivos de Fonte", "*.ttf *.otf"), ("Todos os arquivos", "*.*")]

RESOLUTIONS = ["1080p (1920x1080)", "720p (1280x720)", "Vertical (1080x1920)", "480p (854x480)"]
SUBTITLE_POSITIONS = {
    "Inferior Central": 2, "Inferior Esquerda": 1, "Inferior Direita": 3,
    "Meio Central": 5, "Meio Esquerda": 4, "Meio Direita": 6,
    "Superior Central": 8, "Superior Esquerda": 7, "Superior Direita": 9
}
SLIDESHOW_TRANSITIONS = ["fade", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown", "circlecrop", "rectcrop", "distance", "fadegrays", "radial", "diagtl", "diagtr", "diagbl", "diagbr", "hlslice", "hrslice", "vuslice", "vdslice"]
SLIDESHOW_MOTIONS = ["Nenhum", "Zoom In", "Zoom Out", "Pan Esquerda", "Pan Direita", "Aleatório"]


# --- Logger Global ---
logger = logging.getLogger()


class ConfigManager:
    """Gerencia o carregamento e salvamento da configuração do aplicativo."""
    @staticmethod
    def load_config() -> Dict[str, Any]:
        default_config = {
            'ffmpeg_path': '', 'output_folder': '', 'last_video_folder': '',
            'last_audio_folder': '', 'last_image_folder': '', 'last_srt_folder': '',
            'video_codec': 'Automático', 'resolution': RESOLUTIONS[0],
            'narration_volume': 0, 'music_volume': -15, 'subtitle_fontsize': 28,
            'subtitle_textcolor': '#FFFFFF', 'subtitle_outlinecolor': '#000000',
            'subtitle_position': list(SUBTITLE_POSITIONS.keys())[0], 'subtitle_bold': True,
            'subtitle_italic': False, 'subtitle_font_file': '',
            'image_duration': 5,
            'slideshow_transition': SLIDESHOW_TRANSITIONS[0],
            'slideshow_motion': SLIDESHOW_MOTIONS[1],
        }
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                    if file_content:
                        saved_config = json.loads(file_content)
                        default_config.update(saved_config)
        except Exception as e:
            logger.warning(f"Não foi possível carregar o arquivo de configuração: {e}")
        return default_config

    @staticmethod
    def save_config(config: Dict[str, Any]) -> None:
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erro ao salvar o arquivo de configuração: {e}")


class FFmpegManager:
    """Lida com a descoberta e instalação do FFmpeg."""
    @staticmethod
    def find_executable() -> Optional[str]:
        executable = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            potential_path = os.path.join(path_dir, executable)
            if os.path.isfile(potential_path) and os.access(potential_path, os.X_OK):
                return potential_path
        return None

    @staticmethod
    def check_encoders(ffmpeg_path: str) -> List[str]:
        encoders_found = ["libx264"]
        if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
            return encoders_found
        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            result = subprocess.run(
                [ffmpeg_path, '-encoders'], capture_output=True, text=True, check=True, timeout=10,
                creationflags=creation_flags, encoding='utf-8', errors='ignore'
            )
            if "h264_nvenc" in result.stdout: encoders_found.append("h264_nvenc")
            if "hevc_nvenc" in result.stdout: encoders_found.append("hevc_nvenc")
            logger.info(f"Encoders FFmpeg detectados: {encoders_found}")
        except Exception as e:
            logger.warning(f"Falha ao verificar os encoders do FFmpeg: {e}")
        return encoders_found

class SubtitlePreview(tk.Canvas):
    """Um widget personalizado para fornecer uma visualização realista da legenda."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#1a1a1a", **kwargs)
        self.text_id = self.create_text(0, 0, text="Subtitle Preview", fill="white", anchor="center")
        self.outline_ids = [self.create_text(0, 0, text="Subtitle Preview", fill="black", anchor="center") for _ in range(4)]
        self.tag_lower(self.outline_ids)
        self.tag_raise(self.text_id)
        self.bind("<Configure>", self._on_resize)
        self._font = ("Arial", 28, "bold")

    def _on_resize(self, event):
        self.update_preview()

    def update_preview(self, text="Subtitle Preview", font_config=None, text_color="#FFFFFF", outline_color="#000000", position_key="Inferior Central"):
        if font_config:
            self._font = font_config
        self.itemconfig(self.text_id, text=text, font=self._font, fill=text_color)
        for i in range(4):
            self.itemconfig(self.outline_ids[i], text=text, font=self._font, fill=outline_color)
        width, height = self.winfo_width(), self.winfo_height()
        pos = SUBTITLE_POSITIONS.get(position_key, 2)
        if pos in [7, 8, 9]: rely = 0.15
        elif pos in [4, 5, 6]: rely = 0.5
        else: rely = 0.85
        if pos in [1, 4, 7]: relx, anchor = 0.05, "w"
        elif pos in [3, 6, 9]: relx, anchor = 0.95, "e"
        else: relx, anchor = 0.5, "center"
        x, y = width * relx, height * rely
        self.coords(self.text_id, x, y)
        self.itemconfig(self.text_id, anchor=anchor)
        offsets = [(-2, -2), (2, -2), (2, 2), (-2, 2)]
        for i, (dx, dy) in enumerate(offsets):
            self.coords(self.outline_ids[i], x + dx, y + dy)
            self.itemconfig(self.outline_ids[i], anchor=anchor)

class VideoEditorApp:
    """A classe principal do aplicativo."""
    def __init__(self):
        self.root = ttk.Window(themename="superhero")
        self.root.title(APP_NAME)
        self.root.geometry(DEFAULT_GEOMETRY)
        self.root.minsize(1100, 800)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._setup_logging()
        logger.info("Iniciando aplicativo.")
        self.config = ConfigManager.load_config()
        self._init_variables()
        self._init_state()
        self._create_widgets()
        self.root.after(100, self.post_init_setup)

    def post_init_setup(self):
        self.find_ffmpeg_on_startup()
        self.update_ui_for_media_type()
        self.update_subtitle_preview_job()
        self.check_queue()
        logger.info("Configuração da UI concluída.")

    def _setup_logging(self):
        logger.setLevel(logging.DEBUG)
        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
        try:
            log_file = "video_editor_app.log"
            handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
            handler.setFormatter(log_formatter)
            logger.addHandler(handler)
            logger.info(f"Log configurado. Arquivo de log: {os.path.abspath(log_file)}")
        except Exception as e:
            print(f"Erro ao configurar o log em arquivo: {e}")

    def _init_variables(self):
        self.ffmpeg_path_var = ttk.StringVar(value=self.config.get('ffmpeg_path', ''))
        self.media_path_single = ttk.StringVar(value='')
        self.narration_file_single = ttk.StringVar()
        self.subtitle_file_single = ttk.StringVar()
        self.batch_video_parent_folder = ttk.StringVar()
        self.batch_audio_folder = ttk.StringVar()
        self.batch_srt_folder = ttk.StringVar()
        self.music_file_single = ttk.StringVar()
        self.music_folder_path = ttk.StringVar()
        self.output_folder = ttk.StringVar(value=self.config.get('output_folder', ''))
        self.output_filename_single = ttk.StringVar(value="video_final.mp4")
        self.subtitle_font_file = ttk.StringVar(value=self.config.get('subtitle_font_file', ''))
        self.path_vars = {'narration_single': self.narration_file_single, 'subtitle_single': self.subtitle_file_single, 'media_single': self.media_path_single, 'batch_video': self.batch_video_parent_folder, 'batch_audio': self.batch_audio_folder, 'batch_srt': self.batch_srt_folder, 'music_single': self.music_file_single, 'music_folder': self.music_folder_path, 'output': self.output_folder, 'subtitle_font': self.subtitle_font_file, 'ffmpeg_path': self.ffmpeg_path_var}
        self.media_type = ttk.StringVar(value="video_single")
        self.resolution_var = ttk.StringVar(value=self.config.get('resolution', RESOLUTIONS[0]))
        self.video_codec_var = ttk.StringVar(value=self.config.get('video_codec', 'Automático'))
        self.image_duration_var = ttk.IntVar(value=self.config.get('image_duration', 5))
        self.transition_var = ttk.StringVar(value=self.config.get('slideshow_transition', SLIDESHOW_TRANSITIONS[0]))
        self.motion_var = ttk.StringVar(value=self.config.get('slideshow_motion', SLIDESHOW_MOTIONS[1]))
        self.narration_volume_var = ttk.DoubleVar(value=self.config.get('narration_volume', 0))
        self.music_volume_var = ttk.DoubleVar(value=self.config.get('music_volume', -15))
        self.subtitle_fontsize_var = ttk.IntVar(value=self.config.get('subtitle_fontsize', 28))
        self.subtitle_textcolor_var = ttk.StringVar(value=self.config.get('subtitle_textcolor', '#FFFFFF'))
        self.subtitle_outlinecolor_var = ttk.StringVar(value=self.config.get('subtitle_outlinecolor', '#000000'))
        self.subtitle_position_var = ttk.StringVar(value=self.config.get('subtitle_position', list(SUBTITLE_POSITIONS.keys())[0]))
        self.subtitle_bold_var = ttk.BooleanVar(value=self.config.get('subtitle_bold', True))
        self.subtitle_italic_var = ttk.BooleanVar(value=self.config.get('subtitle_italic', False))

    def _init_state(self):
        self.is_processing = False
        self.cancel_requested = threading.Event()
        self.progress_queue = queue.Queue()
        self.thread_executor = ThreadPoolExecutor(max_workers=1)
        self.available_encoders_cache: Optional[List[str]] = None

    def _create_widgets(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))

        self._create_files_tab()
        self._create_video_tab()
        self._create_audio_tab()
        self._create_subtitle_tab()
        self._create_settings_tab()
        
        self._create_process_and_status_section(self.root)

    def _create_files_tab(self):
        tab = ttk.Frame(self.notebook, padding=(20, 15))
        self.notebook.add(tab, text=" 1. Arquivos ")
        tab.columnconfigure(0, weight=1)

        mode_section = ttk.LabelFrame(tab, text=" Modo de Operação ", padding=15)
        mode_section.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        ttk.Radiobutton(mode_section, text="Vídeo Único", variable=self.media_type, value="video_single", command=self.update_ui_for_media_type).pack(side=LEFT, padx=(0, 20))
        ttk.Radiobutton(mode_section, text="Slideshow de Imagens", variable=self.media_type, value="image_folder", command=self.update_ui_for_media_type).pack(side=LEFT, padx=(0, 20))
        ttk.Radiobutton(mode_section, text="Lote de Vídeos", variable=self.media_type, value="batch", command=self.update_ui_for_media_type).pack(side=LEFT)

        input_section = ttk.LabelFrame(tab, text=" Arquivos de Entrada ", padding=15)
        input_section.grid(row=1, column=0, sticky="ew", pady=(0, 15))
        input_section.columnconfigure(0, weight=1)
        
        self.single_inputs_frame = ttk.Frame(input_section); self.single_inputs_frame.grid(row=0, column=0, sticky="ew"); self.single_inputs_frame.columnconfigure(0, weight=1)
        self.media_path_label_widget = self._create_file_input(self.single_inputs_frame, 0, "Mídia Principal:", 'media_single', self.select_media_single)
        self._create_file_input(self.single_inputs_frame, 1, "Narração (Áudio):", 'narration_single', lambda: self.select_file('narration_single', "Selecione a Narração", SUPPORTED_NARRATION_FT))
        self._create_file_input(self.single_inputs_frame, 2, "Legenda (SRT):", 'subtitle_single', lambda: self.select_file('subtitle_single', "Selecione a Legenda", SUPPORTED_SUBTITLE_FT))
        
        self.batch_inputs_frame = ttk.Frame(input_section); self.batch_inputs_frame.grid(row=0, column=0, sticky="ew"); self.batch_inputs_frame.columnconfigure(0, weight=1)
        self._create_file_input(self.batch_inputs_frame, 0, "Pasta de Vídeos:", 'batch_video', lambda: self.select_folder('batch_video', "Selecione a Pasta de Vídeos"))
        self._create_file_input(self.batch_inputs_frame, 1, "Pasta de Áudios:", 'batch_audio', lambda: self.select_folder('batch_audio', "Selecione a Pasta de Áudios"))
        self._create_file_input(self.batch_inputs_frame, 2, "Pasta de Legendas:", 'batch_srt', lambda: self.select_folder('batch_srt', "Selecione a Pasta de Legendas"))
        
        music_section = ttk.LabelFrame(tab, text=" Música de Fundo (Opcional) ", padding=15)
        music_section.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        music_section.columnconfigure(0, weight=1)
        self.music_file_frame = self._create_file_input(music_section, 0, "Arquivo de Música:", 'music_single', lambda: self.select_file('music_single', "Selecione a Música", SUPPORTED_MUSIC_FT))
        self.music_folder_frame = self._create_file_input(music_section, 0, "Pasta de Músicas:", 'music_folder', lambda: self.select_folder('music_folder', "Selecione a Pasta de Músicas"))
        
        output_section = ttk.LabelFrame(tab, text=" Arquivo de Saída ", padding=15)
        output_section.grid(row=3, column=0, sticky="ew")
        output_section.columnconfigure(0, weight=1)
        self._create_file_input(output_section, 0, "Pasta de Saída:", 'output', lambda: self.select_folder('output', "Selecione a Pasta de Saída"))
        
        self.output_filename_frame = ttk.Frame(output_section)
        self.output_filename_frame.grid(row=1, column=0, sticky="ew", pady=4)
        self.output_filename_frame.columnconfigure(1, weight=1)
        ttk.Label(self.output_filename_frame, text="Nome do Arquivo:", width=20, anchor='w').grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(self.output_filename_frame, textvariable=self.output_filename_single).grid(row=0, column=1, sticky="ew")

    def _create_video_tab(self):
        tab = ttk.Frame(self.notebook, padding=(20, 15))
        self.notebook.add(tab, text=" 2. Vídeo ")
        tab.columnconfigure(0, weight=1)
        
        self.video_settings_section = ttk.LabelFrame(tab, text=" Configurações Gerais de Vídeo ", padding=15)
        self.video_settings_section.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        self.video_settings_section.columnconfigure(1, weight=1)
        ttk.Label(self.video_settings_section, text="Resolução:").grid(row=0, column=0, sticky="w", padx=(0,10), pady=5)
        ttk.Combobox(self.video_settings_section, textvariable=self.resolution_var, values=RESOLUTIONS, state="readonly").grid(row=0, column=1, sticky="ew")
        ttk.Label(self.video_settings_section, text="Codificador:").grid(row=1, column=0, sticky="w", padx=(0,10), pady=5)
        self.video_codec_combobox = ttk.Combobox(self.video_settings_section, textvariable=self.video_codec_var, state="readonly")
        self.video_codec_combobox.grid(row=1, column=1, sticky="ew")
        
        self.slideshow_section = ttk.LabelFrame(tab, text=" Configurações de Slideshow ", padding=15)
        self.slideshow_section.grid(row=1, column=0, sticky="ew")
        self.slideshow_section.columnconfigure(1, weight=1)
        ttk.Label(self.slideshow_section, text="Duração por Imagem (s):").grid(row=0, column=0, sticky="w", padx=(0,10), pady=5)
        duration_frame = ttk.Frame(self.slideshow_section); duration_frame.grid(row=0, column=1, sticky="ew"); duration_frame.columnconfigure(0, weight=1)
        ttk.Scale(duration_frame, from_=1, to=30, variable=self.image_duration_var, orient=HORIZONTAL, command=lambda v: self.image_duration_var.set(int(float(v)))).grid(row=0, column=0, sticky="ew", padx=(0,10))
        ttk.Label(duration_frame, textvariable=self.image_duration_var, width=3).grid(row=0, column=1)
        ttk.Label(self.slideshow_section, text="Transição:").grid(row=1, column=0, sticky="w", padx=(0,10), pady=5)
        ttk.Combobox(self.slideshow_section, textvariable=self.transition_var, values=SLIDESHOW_TRANSITIONS, state="readonly").grid(row=1, column=1, sticky="ew")
        ttk.Label(self.slideshow_section, text="Efeito de Movimento:").grid(row=2, column=0, sticky="w", padx=(0,10), pady=5)
        ttk.Combobox(self.slideshow_section, textvariable=self.motion_var, values=SLIDESHOW_MOTIONS, state="readonly").grid(row=2, column=1, sticky="ew")

    def _create_audio_tab(self):
        tab = ttk.Frame(self.notebook, padding=(20, 15))
        self.notebook.add(tab, text=" 3. Áudio ")
        tab.columnconfigure(0, weight=1)
        audio_settings_section = ttk.LabelFrame(tab, text=" Volumes ", padding=15)
        audio_settings_section.grid(row=0, column=0, sticky="ew")
        audio_settings_section.columnconfigure(1, weight=1)
        
        self._create_volume_slider(audio_settings_section, 0, "Volume da Narração:", self.narration_volume_var, -20, 20)
        self._create_volume_slider(audio_settings_section, 1, "Volume da Música:", self.music_volume_var, -60, 0)
        
    def _create_volume_slider(self, parent, row, label_text, var, from_, to):
        ttk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", padx=(0,10), pady=10)
        slider_frame = ttk.Frame(parent)
        slider_frame.grid(row=row, column=1, sticky="ew")
        slider_frame.columnconfigure(0, weight=1)
        
        display_var = ttk.StringVar()
        def update_display(v):
            val = int(float(v))
            var.set(val)
            display_var.set(f"{val} dB")
        
        ttk.Scale(slider_frame, from_=from_, to=to, variable=var, orient=HORIZONTAL, command=update_display).grid(row=0, column=0, sticky="ew", padx=(0,10))
        ttk.Label(slider_frame, textvariable=display_var, width=7).grid(row=0, column=1)
        update_display(var.get())

    def _create_subtitle_tab(self):
        tab = ttk.Frame(self.notebook, padding=(20, 15))
        self.notebook.add(tab, text=" 4. Legendas ")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        
        settings_frame = ttk.LabelFrame(tab, text=" Estilo da Legenda ", padding=15)
        settings_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)
        
        self._create_font_size_slider(settings_frame, 0, 0)
        ttk.Label(settings_frame, text="Posição:").grid(row=0, column=2, sticky="w", padx=(20,10), pady=5)
        pos_combo = ttk.Combobox(settings_frame, textvariable=self.subtitle_position_var, values=list(SUBTITLE_POSITIONS.keys()), state="readonly")
        pos_combo.grid(row=0, column=3, sticky="ew")
        pos_combo.bind('<<ComboboxSelected>>', self.on_subtitle_style_change)
        
        ttk.Label(settings_frame, text="Cor do Texto:").grid(row=1, column=0, sticky="w", padx=(0,10), pady=5)
        self._create_color_picker(settings_frame, 1, self.subtitle_textcolor_var)
        ttk.Label(settings_frame, text="Cor do Contorno:").grid(row=1, column=2, sticky="w", padx=(20,10), pady=5)
        self._create_color_picker(settings_frame, 3, self.subtitle_outlinecolor_var)

        style_frame = ttk.Frame(settings_frame)
        style_frame.grid(row=2, column=1, sticky="w", pady=5)
        ttk.Checkbutton(style_frame, text="Negrito", variable=self.subtitle_bold_var, bootstyle="round-toggle", command=self.on_subtitle_style_change).pack(side=LEFT, padx=(0, 10))
        ttk.Checkbutton(style_frame, text="Itálico", variable=self.subtitle_italic_var, bootstyle="round-toggle", command=self.on_subtitle_style_change).pack(side=LEFT)
        
        font_frame = self._create_file_input(settings_frame, 3, "Arquivo de Fonte:", 'subtitle_font', lambda: self.select_file('subtitle_font', "Selecione a Fonte", SUPPORTED_FONT_FT))
        font_frame.grid(row=2, column=2, columnspan=2, sticky='ew', padx=(20, 0))

        preview_section = ttk.LabelFrame(tab, text=" Preview da Legenda ", padding=5)
        preview_section.grid(row=1, column=0, sticky="nsew")
        preview_section.rowconfigure(0, weight=1)
        preview_section.columnconfigure(0, weight=1)
        self.subtitle_preview = SubtitlePreview(preview_section)
        self.subtitle_preview.grid(row=0, column=0, sticky="nsew")
        
    def _create_font_size_slider(self, parent, row, col):
        ttk.Label(parent, text="Tamanho:").grid(row=row, column=col, sticky="w", padx=(0,10), pady=5)
        font_size_frame = ttk.Frame(parent)
        font_size_frame.grid(row=row, column=col+1, sticky="ew")
        font_size_frame.columnconfigure(0, weight=1)
        
        display_var = ttk.StringVar()
        def update_display(v):
            val = int(float(v))
            self.subtitle_fontsize_var.set(val)
            display_var.set(str(val))
            self.on_subtitle_style_change()
            
        ttk.Scale(font_size_frame, from_=10, to=100, variable=self.subtitle_fontsize_var, orient=HORIZONTAL, command=update_display).grid(row=0, column=0, sticky="ew", padx=(0,10))
        ttk.Label(font_size_frame, textvariable=display_var, width=3).grid(row=0, column=1)
        update_display(self.subtitle_fontsize_var.get())

    def _create_settings_tab(self):
        tab = ttk.Frame(self.notebook, padding=(20, 15))
        self.notebook.add(tab, text=" 5. Configurações ")
        tab.columnconfigure(0, weight=1)
        
        ffmpeg_section = ttk.LabelFrame(tab, text=" FFmpeg ", padding=15)
        ffmpeg_section.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        ffmpeg_section.columnconfigure(0, weight=1)
        
        ffmpeg_path_frame = self._create_file_input(ffmpeg_section, 0, "Caminho do FFmpeg:", 'ffmpeg_path', self.ask_ffmpeg_path_manual)
        
        status_frame = ttk.Frame(ffmpeg_section)
        status_frame.grid(row=1, column=0, sticky='ew', pady=(10,0))
        install_button = ttk.Button(status_frame, text="Instalar FFmpeg (Windows)", command=self.install_ffmpeg_automatically, bootstyle="info-outline")
        install_button.pack(side=LEFT, anchor='w')
        ToolTip(install_button, "Baixa e configura o FFmpeg automaticamente. Requer conexão com a internet.")
        self.ffmpeg_status_label = ttk.Label(status_frame, text="Verificando...", bootstyle="secondary")
        self.ffmpeg_status_label.pack(side=LEFT, padx=15, anchor='w')

    def _create_process_and_status_section(self, parent):
        parent.rowconfigure(1, weight=1) 
        
        bottom_container = ttk.Frame(parent, padding=(10,0,10,10))
        bottom_container.grid(row=1, column=0, sticky='nsew')
        bottom_container.columnconfigure(0, weight=1)
        bottom_container.rowconfigure(1, weight=1)
        
        action_frame = ttk.LabelFrame(bottom_container, text=" Ações e Progresso ", padding=15)
        action_frame.grid(row=0, column=0, sticky="ew", pady=(10, 10))
        action_frame.columnconfigure(1, weight=1)
        
        button_frame = ttk.Frame(action_frame)
        button_frame.grid(row=0, column=0, rowspan=2, padx=(0, 20), sticky='n')
        self.start_button = ttk.Button(button_frame, text="▶ Iniciar", command=self.start_processing_controller, bootstyle="success", width=12)
        self.start_button.pack(pady=(0, 5), ipady=2)
        self.cancel_button = ttk.Button(button_frame, text="⏹ Cancelar", command=self.request_cancellation, state=DISABLED, bootstyle="danger-outline", width=12)
        self.cancel_button.pack(pady=5, ipady=2)
        
        ttk.Label(action_frame, text="Progresso do Item:").grid(row=0, column=1, sticky="w", pady=(0,5))
        self.progress_bar = ttk.Progressbar(action_frame, mode='determinate', bootstyle="success-striped")
        self.progress_bar.grid(row=0, column=2, sticky="ew", padx=10, pady=(0,5))
        
        self.batch_progress_frame = ttk.Frame(action_frame)
        self.batch_progress_frame.grid(row=1, column=1, columnspan=2, sticky="ew")
        self.batch_progress_frame.columnconfigure(1, weight=1)
        ttk.Label(self.batch_progress_frame, text="Progresso do Lote:").grid(row=0, column=0, sticky="w")
        self.batch_progress_bar = ttk.Progressbar(self.batch_progress_frame, mode='determinate', bootstyle="info-striped")
        self.batch_progress_bar.grid(row=0, column=1, sticky="ew", padx=10)
        
        log_frame = ttk.LabelFrame(bottom_container, text=" Logs de Processamento ", padding=(15, 10))
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.status_text = tk.Text(log_frame, height=8, wrap=WORD, font=('Consolas', 9), relief="flat", background=self.root.style.colors.bg)
        scrollbar = ttk.Scrollbar(log_frame, orient=VERTICAL, command=self.status_text.yview, bootstyle="round")
        self.status_text.configure(yscrollcommand=scrollbar.set, state=DISABLED)
        self.status_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.status_text.tag_configure("error", foreground=self.root.style.colors.danger)
        self.status_text.tag_configure("success", foreground=self.root.style.colors.success)
        self.status_text.tag_configure("info", foreground=self.root.style.colors.info)
        self.status_text.tag_configure("warning", foreground=self.root.style.colors.warning)

    def _create_file_input(self, parent, row, label_text, var_key, command):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=4)
        frame.columnconfigure(1, weight=1)
        
        ttk.Label(frame, text=label_text, width=20, anchor='w').grid(row=0, column=0, sticky="w", padx=(0, 10))
        
        entry = ttk.Entry(frame, textvariable=self.path_vars[var_key], state="readonly")
        entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        
        button = ttk.Button(frame, text="Selecionar...", command=command, bootstyle="secondary-outline", width=12)
        button.grid(row=0, column=2, sticky="e")
            
        return frame

    def _create_color_picker(self, parent, column, variable):
        frame = ttk.Frame(parent)
        frame.grid(row=1, column=column, sticky="ew", padx=(0, 10))
        entry = ttk.Entry(frame, textvariable=variable, width=10)
        entry.pack(side=LEFT, fill=X, expand=True)
        entry.bind("<KeyRelease>", self.on_subtitle_style_change)
        button = ttk.Button(frame, text="🎨", width=3, bootstyle="info-outline", command=lambda: self.select_color(variable))
        button.pack(side=LEFT, padx=(5,0))

    def on_subtitle_style_change(self, event=None):
        if hasattr(self, '_subtitle_update_job'): self.root.after_cancel(self._subtitle_update_job)
        self._subtitle_update_job = self.root.after(100, self.update_subtitle_preview_job)
        
    def update_subtitle_preview_job(self):
        if not hasattr(self, 'subtitle_preview'): return
        try:
            font_size = int(self.subtitle_fontsize_var.get())
            weight = "bold" if self.subtitle_bold_var.get() else "normal"
            slant = "italic" if self.subtitle_italic_var.get() else "roman"
            font_tuple = (tkFont.Font(family="Arial", size=font_size, weight=weight, slant=slant))
            self.subtitle_preview.update_preview(font_config=font_tuple, text_color=self.subtitle_textcolor_var.get(), outline_color=self.subtitle_outlinecolor_var.get(), position_key=self.subtitle_position_var.get())
        except (tk.TclError, ValueError) as e:
            logger.warning(f"Erro ao atualizar a pré-visualização da legenda: {e}")

    def update_ui_for_media_type(self, event=None):
        mode = self.media_type.get()
        is_batch = (mode == "batch")
        is_slideshow = (mode == "image_folder")
        
        for frame, show in [(self.single_inputs_frame, not is_batch),
                             (self.batch_inputs_frame, is_batch),
                             (self.music_file_frame, not is_batch),
                             (self.music_folder_frame, is_batch),
                             (self.output_filename_frame, not is_batch),
                             (self.batch_progress_frame, is_batch),
                             (self.slideshow_section, is_slideshow)]:
            frame.grid_remove()
            if show: frame.grid()

        self.media_path_label_widget.winfo_children()[0].config(text="Pasta de Imagens:" if is_slideshow else "Arquivo de Vídeo:")
        self.notebook.tab(1, text="2. Slideshow" if is_slideshow else "2. Vídeo")
        self.video_settings_section.grid()

    def select_media_single(self):
        if self.media_type.get() == "image_folder": self.select_folder('media_single', "Selecione a Pasta de Imagens")
        else: self.select_file('media_single', "Selecione o Arquivo de Vídeo", SUPPORTED_VIDEO_FT)

    def select_file(self, var_key, title, filetypes):
        variable = self.path_vars[var_key]
        last_dir = os.path.dirname(variable.get()) if variable.get() else self.config.get('output_folder')
        filepath = tkinter.filedialog.askopenfilename(title=title, filetypes=filetypes, initialdir=last_dir, parent=self.root)
        if filepath: variable.set(filepath)
    
    def select_folder(self, var_key, title):
        variable = self.path_vars[var_key]
        last_dir = variable.get() if variable.get() else self.config.get('output_folder')
        folderpath = tkinter.filedialog.askdirectory(title=title, initialdir=last_dir, parent=self.root)
        if folderpath: variable.set(folderpath)

    def select_color(self, variable):
        color = tkinter.colorchooser.askcolor(title="Escolha uma cor", initialcolor=variable.get(), parent=self.root)
        if color and color[1]: variable.set(color[1].upper()); self.on_subtitle_style_change()

    def install_ffmpeg_automatically(self):
        if platform.system() != "Windows": Messagebox.show_info("A instalação automática só é suportada no Windows.", "Info", parent=self.root); return
        if self.is_processing: Messagebox.show_warning("Aguarde o término do processamento atual.", "Aviso", parent=self.root); return
        if not Messagebox.yesno("Isso irá baixar o FFmpeg (aproximadamente 80MB) da internet. Deseja continuar?", "Instalar FFmpeg", parent=self.root): return
        threading.Thread(target=self._installation_thread_worker, daemon=True).start()

    def _installation_thread_worker(self):
        self.progress_queue.put(("status", "Iniciando download do FFmpeg...", "info"))
        try:
            ffmpeg_dir = Path.cwd() / "ffmpeg"; ffmpeg_dir.mkdir(exist_ok=True)
            ffmpeg_exe_path = ffmpeg_dir / "bin" / "ffmpeg.exe"
            if ffmpeg_exe_path.exists():
                self.progress_queue.put(("status", "FFmpeg já parece estar instalado localmente.", "info"))
                self.ffmpeg_path_var.set(str(ffmpeg_exe_path.resolve())); return

            url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            zip_path = ffmpeg_dir / "ffmpeg.zip"
            with urllib.request.urlopen(url) as response, open(zip_path, 'wb') as out_file:
                 total_size = int(response.info().get('Content-Length', 0)); chunk_size = 8192; downloaded = 0
                 while True:
                     chunk = response.read(chunk_size)
                     if not chunk: break
                     out_file.write(chunk); downloaded += len(chunk)
                     if total_size > 0: self.progress_queue.put(("status", f"Baixando FFmpeg... {int((downloaded/total_size)*100)}%", "info"))
            self.progress_queue.put(("status", "Download completo. Extraindo...", "info"))
            with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(ffmpeg_dir)
            zip_path.unlink()
            
            found_exe = next(ffmpeg_dir.glob("**/bin/ffmpeg.exe"), None)
            if found_exe:
                self.ffmpeg_path_var.set(str(found_exe.resolve()))
                self.progress_queue.put(("messagebox", "info", "Sucesso", "FFmpeg instalado com sucesso!"))
            else: raise FileNotFoundError("ffmpeg.exe não encontrado no arquivo baixado.")
        except Exception as e:
            logger.error(f"Falha na instalação do FFmpeg: {e}", exc_info=True)
            self.progress_queue.put(("messagebox", "error", "Erro na Instalação", f"Falha ao instalar o FFmpeg: {e}"))
        finally: self.progress_queue.put(("ffmpeg_check",))

    def find_ffmpeg_on_startup(self):
        local_ffmpeg = next(Path.cwd().glob("ffmpeg/bin/ffmpeg.exe"), None)
        configured_path = self.ffmpeg_path_var.get()
        path_from_env = FFmpegManager.find_executable()

        if local_ffmpeg and local_ffmpeg.is_file(): path_to_use = str(local_ffmpeg.resolve())
        elif configured_path and os.path.isfile(configured_path): path_to_use = configured_path
        elif path_from_env: path_to_use = path_from_env
        else: path_to_use = ""
        
        self.ffmpeg_path_var.set(path_to_use)
        logger.info(f"Usando FFmpeg de: {path_to_use if path_to_use else 'Nenhum encontrado'}")
        self.update_ffmpeg_status()

    def update_ffmpeg_status(self):
        is_ok = self.ffmpeg_path_var.get() and os.path.isfile(self.ffmpeg_path_var.get())
        self.ffmpeg_status_label.config(text="FFmpeg OK" if is_ok else "Não encontrado", bootstyle="success" if is_ok else "danger")
        if is_ok: self._check_available_encoders()

    def ask_ffmpeg_path_manual(self):
        filetypes = [("Executáveis", "*.exe"), ("Todos", "*.*")] if platform.system() == "Windows" else [("Todos", "*")]
        filepath = tkinter.filedialog.askopenfilename(title="Selecione o executável do FFmpeg", filetypes=filetypes, parent=self.root)
        if filepath and "ffmpeg" in os.path.basename(filepath).lower(): self.ffmpeg_path_var.set(filepath)
        elif filepath: Messagebox.show_error("Este não parece ser um executável FFmpeg válido.", "Erro", parent=self.root)
        self.update_ffmpeg_status()

    def _check_available_encoders(self):
        self.available_encoders_cache = FFmpegManager.check_encoders(self.ffmpeg_path_var.get())
        options = ["Automático", "CPU (libx264)"]
        if "h264_nvenc" in self.available_encoders_cache: options.append("GPU (NVENC H.264)")
        if "hevc_nvenc" in self.available_encoders_cache: options.append("GPU (NVENC HEVC)")
        self.video_codec_combobox.config(values=options)
        if self.video_codec_var.get() not in options: self.video_codec_var.set("Automático")

    def validate_inputs(self) -> bool:
        logger.info("Validando entradas...")
        if not self.ffmpeg_path_var.get() or not os.path.isfile(self.ffmpeg_path_var.get()):
            Messagebox.show_error("Caminho do FFmpeg inválido.", "Erro de Configuração", parent=self.root); self.notebook.select(4); return False
        if not self.output_folder.get() or not os.path.isdir(self.output_folder.get()):
            Messagebox.show_error("Pasta de saída inválida.", "Erro de Saída", parent=self.root); return False
        
        mode = self.media_type.get()
        if mode == "video_single" and not os.path.isfile(self.media_path_single.get()): Messagebox.show_error("Arquivo de vídeo principal inválido.", "Erro de Entrada", parent=self.root); return False
        if mode == "image_folder" and not os.path.isdir(self.media_path_single.get()): Messagebox.show_error("Pasta de imagens inválida.", "Erro de Entrada", parent=self.root); return False
        if mode == "batch" and (not os.path.isdir(self.batch_video_parent_folder.get()) or not os.path.isdir(self.batch_audio_folder.get())): Messagebox.show_error("Pastas de lote inválidas.", "Erro de Entrada", parent=self.root); return False
        
        logger.info("Entradas validadas com sucesso.")
        return True

    def start_processing_controller(self):
        if self.is_processing: Messagebox.show_warning("Um processamento já está em andamento.", "Aviso", parent=self.root); return
        if not self.validate_inputs(): return
        if video_processing_logic is None: Messagebox.show_error("O módulo 'video_processing_logic.py' não foi encontrado.", "Erro Crítico", parent=self.root); return
        
        self.is_processing = True
        self.cancel_requested.clear()
        self.start_button.config(state=DISABLED)
        self.cancel_button.config(state=NORMAL)
        
        self.progress_bar.config(bootstyle="success-striped"); self.progress_bar['value'] = 0
        self.batch_progress_bar.config(bootstyle="info-striped"); self.batch_progress_bar['value'] = 0

        self.update_status_textbox("Iniciando processamento...", append=False, tag="info")
        params = self._gather_processing_params()
        future = self.thread_executor.submit(video_processing_logic.process_entrypoint, params, self.progress_queue, self.cancel_requested)
        future.add_done_callback(self._processing_thread_done_callback)

    def _gather_processing_params(self) -> Dict[str, Any]:
        params = {var_name.replace("_var", ""): var_obj.get() for var_name, var_obj in self.__dict__.items() if isinstance(var_obj, tk.Variable)}
        params['available_encoders'] = self.available_encoders_cache
        params['subtitle_style'] = {'fontsize': self.subtitle_fontsize_var.get(), 'text_color': self.subtitle_textcolor_var.get(), 'outline_color': self.subtitle_outlinecolor_var.get(), 'bold': self.subtitle_bold_var.get(), 'italic': self.subtitle_italic_var.get(), 'position': self.subtitle_position_var.get(), 'font_file': self.subtitle_font_file.get(), 'position_map': SUBTITLE_POSITIONS}
        return params

    def request_cancellation(self):
        if self.is_processing:
            logger.info("Cancelamento solicitado pelo usuário.")
            self.cancel_requested.set()
            self.cancel_button.config(state=DISABLED)
            self.update_status_textbox("Cancelamento solicitado... Aguardando a tarefa terminar.", tag="warning")

    def _processing_thread_done_callback(self, future):
        try: future.result()
        except Exception as e:
            logger.error(f"Exceção na thread de processamento: {e}", exc_info=True)
            self.progress_queue.put(("status", f"Erro fatal na thread: {e}", "error"))
        finally:
            self.progress_queue.put(("finish", False))

    def _finalize_processing_ui_state(self, success: bool):
        self.is_processing = False
        self.start_button.config(state=NORMAL)
        self.cancel_button.config(state=DISABLED)
        final_style = "success" if success else "danger"
        self.progress_bar.config(bootstyle=final_style)
        self.batch_progress_bar.config(bootstyle=f"info-{final_style}")

    def check_queue(self):
        try:
            while True:
                msg_type, *payload = self.progress_queue.get_nowait()
                if msg_type == "status": self.update_status_textbox(payload[0], tag=payload[1])
                elif msg_type == "progress": self.progress_bar['value'] = payload[0] * 100
                elif msg_type == "batch_progress": self.batch_progress_bar['value'] = payload[0] * 100
                elif msg_type == "finish": self._finalize_processing_ui_state(success=payload[0])
                elif msg_type == "ffmpeg_check": self.update_ffmpeg_status()
                elif msg_type == "messagebox": Messagebox.show_info(payload[2], payload[1], parent=self.root) if payload[0] == 'info' else Messagebox.show_error(payload[2], payload[1], parent=self.root)
        except queue.Empty: pass
        finally: self.root.after(100, self.check_queue)
    
    def update_status_textbox(self, text: str, append: bool = True, tag: str = "info"):
        self.status_text.config(state=NORMAL)
        full_log_line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {text}\n"
        if not append: self.status_text.delete("1.0", END)
        self.status_text.insert(END, full_log_line, tag)
        self.status_text.see(END)
        self.status_text.config(state=DISABLED)
        logger.log(logging.INFO if tag != "error" else logging.ERROR, text)

    def save_current_config(self):
        config_to_save = {
            'ffmpeg_path': self.ffmpeg_path_var.get(),
            'output_folder': self.output_folder.get(),
            'video_codec': self.video_codec_var.get(),
            'resolution': self.resolution_var.get(),
            'narration_volume': self.narration_volume_var.get(),
            'music_volume': self.music_volume_var.get(),
            'subtitle_fontsize': self.subtitle_fontsize_var.get(),
            'subtitle_textcolor': self.subtitle_textcolor_var.get(),
            'subtitle_outlinecolor': self.subtitle_outlinecolor_var.get(),
            'subtitle_position': self.subtitle_position_var.get(),
            'subtitle_bold': self.subtitle_bold_var.get(),
            'subtitle_italic': self.subtitle_italic_var.get(),
            'subtitle_font_file': self.subtitle_font_file.get(),
            'image_duration': self.image_duration_var.get(),
            'slideshow_transition': self.transition_var.get(),
            'slideshow_motion': self.motion_var.get(),
        }
        ConfigManager.save_config(config_to_save)
        logger.info("Configuração salva.")

    def on_closing(self):
        logger.info("Botão de fechar clicado.")
        if self.is_processing:
            if Messagebox.yesno("Um processamento está em andamento. Deseja realmente sair e cancelar a tarefa?", "Sair?", parent=self.root):
                self.request_cancellation()
        else:
            self.save_current_config()
            self.thread_executor.shutdown(wait=False, cancel_futures=True)
            if video_processing_logic and hasattr(video_processing_logic, 'process_manager'):
                video_processing_logic.process_manager.shutdown()
            logger.info("Aplicativo fechado.")
            self.root.destroy()


def run_app():
    """Inicializa e executa a interface gráfica"""
    if platform.system() == "Windows":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception as e:
            print(f"Não foi possível definir a conscientização de DPI: {e}")
    if not os.path.exists("video_processing_logic.py"):
        error_msg = "ERRO CRÍTICO: O arquivo 'video_processing_logic.py' não foi encontrado."
        root = tk.Tk(); root.withdraw()
        Messagebox.show_error(error_msg, "Arquivo Faltando")
        return
    app = VideoEditorApp()
    app.root.mainloop()

__all__ = ["run_app", "VideoEditorApp"]
