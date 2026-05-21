# src/utils/app_paths.py
from pathlib import Path
import sys

def get_app_data_dir():
    """
    Возвращает путь к директории приложения.
    
    ВСЕГДА возвращает ~/Documents/SculptorPro/
    (и в dev-режиме, и в production)
    
    macOS: ~/Documents/SculptorPro/
    Windows: ~/Documents/SculptorPro/
    Linux: ~/.sculptorpro/
    """
    if sys.platform == 'darwin':  # macOS
        base = Path.home() / "Documents" / "SculptorPro"
    elif sys.platform == 'win32':  # Windows
        base = Path.home() / "Documents" / "SculptorPro"
    else:  # Linux
        base = Path.home() / ".sculptorpro"
    
    # Создаём папку, если её нет
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_library_path():
    """Путь к библиотеке фильмов: ~/Documents/SculptorPro/_library"""
    path = get_app_data_dir() / "_library"
    path.mkdir(exist_ok=True)
    return path


def get_projects_path():
    """Путь к проектам: ~/Documents/SculptorPro/projects"""
    path = get_app_data_dir() / "projects"
    path.mkdir(exist_ok=True)
    return path


def get_config_path():
    """Путь к конфигурации: ~/Documents/SculptorPro/config.yaml"""
    return get_app_data_dir() / "config.yaml"


def get_studio_path():
    """Путь к студии: ~/Documents/SculptorPro/_studio"""
    path = get_app_data_dir() / "_studio"
    path.mkdir(exist_ok=True)
    return path


def ensure_app_structure():
    """
    Создает структуру папок при первом запуске.
    Вызывается при старте сервера.
    
    Возвращает путь к корневой папке приложения.
    """
    app_dir = get_app_data_dir()
    
    # Создаем основные директории
    library = get_library_path()
    projects = get_projects_path()
    studio = get_studio_path()
    
    # Создаем placeholder файлы (для визуальной красоты в Finder)
    lib_placeholder = library / "placeholder.txt"
    if not lib_placeholder.exists():
        lib_placeholder.write_text(
            "This folder stores your indexed movie footage.\n"
            "Each subfolder represents one film."
        )
    
    proj_placeholder = projects / "placeholder.txt"
    if not proj_placeholder.exists():
        proj_placeholder.write_text(
            "This folder stores your editing projects.\n"
            "Each subfolder contains project files and outputs."
        )
    
    # Копируем/создаём config.yaml, если его нет
    config_path = get_config_path()
    if not config_path.exists():
        default_config = """# SculptorPro Configuration
# Этот файл создан автоматически

paths:
  library: "_library"
  projects: "projects"

models:
  whisper: "small"
  gemini: "gemini-3.1-flash-lite-preview"
  clip: "ViT-B/32"
  face_detection: "buffalo_s"
"""
        config_path.write_text(default_config)
        print(f"✅ Created default config at: {config_path}")
    
    print(f"📂 App structure ready at: {app_dir}")
    return app_dir
