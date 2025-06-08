import sys


def print_usage():
    """Exibe instruções de uso básicas."""
    print("Uso: python main.py [--help]")
    print("Sem argumentos, abre a interface gráfica do editor.")


def start_gui():
    from video_editor_gui import run_app
    run_app()


if '--help' in sys.argv or '-h' in sys.argv:
    print_usage()
else:
    if __name__ == '__main__':
        start_gui()
