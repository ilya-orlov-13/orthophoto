import logging
import os
import multiprocessing # Для определения количества ядер CPU

# --- Определение корневой папки проекта ---
# __file__ - это путь к текущему файлу (config.py)
# os.path.dirname() - получает директорию, в которой лежит файл
# os.path.abspath() - получает абсолютный путь
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Основные пути (относительно PROJECT_ROOT) ---
# ODM будет искать изображения в папке 'images' внутри корня проекта
INPUT_IMAGE_DIR_REL = 'data/input_images'
# ODM создаст папку с именем ODM_PROJECT_NAME ВНУТРИ корня проекта (PROJECT_ROOT)
OUTPUT_DIR_REL = 'data/output'
# Пути для модуля анализа (остаются в data/)
PARKING_LAYOUT_DIR_REL = 'data/parking_layout'
MODELS_DIR_REL = 'models'

# --- Параметры запуска ODM (для odm_runner.py) ---
ODM_RUN_METHOD = 'docker'                 # Метод запуска: 'docker' или 'native'
ODM_DOCKER_IMAGE = 'opendronemap/odm:latest' # Docker образ ODM (можно 'opendronemap/odm:3.1.1' и т.д.)
ODM_PROJECT_NAME = "odm_processing"

ODM_OPTIONS = {
    "dsm": True,                      # Генерировать DSM?
    "orthophoto-resolution": 5.0,     # Разрешение ортофото в СМ/пиксель
    # "orthophoto-tif": True,        

    # --- Качество/Скорость ---
    "feature-quality": "medium",
    "pc-quality": "medium",
    "use-gpu": True,                  # Пытаться использовать GPU?
    "max-concurrency": max(1, multiprocessing.cpu_count() // 2),
    # "resize-to": 2400,
    "fast-orthophoto": False,
    "matcher-type": "flann",
}

# --- Параметры анализа парковок (для analysis.py) ---
RUN_PARKING_ANALYSIS = False             # Включить/выключить анализ
PARKING_ANALYSIS_PARAMS = {
    'model_filename': 'yolov8s_parking_best.pt', # Имя файла модели YOLO (.pt) в папке MODELS_DIR_REL
    'slot_filename': 'parking_slots_layout.json',# Имя файла разметки в PARKING_LAYOUT_DIR_REL
    'confidence_threshold': 0.4,       # Порог уверенности для детекции YOLO
    'iou_threshold': 0.5                 # Порог IoU для NMS (если используется)
}
ANALYSIS_RESULTS_FILENAME = 'parking_analysis_results.json' # Имя файла для сохранения результатов анализа (в OUTPUT_DIR_REL)

USE_LLM_ASSISTANT = False                 # Использовать LLM для генерации отчета?
LM_STUDIO_API_BASE = "http://localhost:1234/v1" # URL сервера LM Studio
LM_STUDIO_MODEL_NAME = "local-model"      # Имя модели для API
LLM_REPORT_PARAMS = {
    'max_tokens': 350,
    'temperature': 0.6
}
REPORT_FILENAME = "processing_report.txt" # Имя файла для отчета (в OUTPUT_DIR_REL)

# --- Настройки логирования (для helpers.py) ---
LOGGING_LEVEL = 'INFO'                    # Уровни: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_TO_FILE = True                        # Записывать ли лог в файл?
LOG_FILENAME = 'orthophoto_analyzer.log'  # Имя файла лога (будет сохранен в OUTPUT_DIR_REL)
