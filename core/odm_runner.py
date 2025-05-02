import subprocess
import os
import logging
import shlex
from typing import Dict, Any, Optional
# Импортируем хелперы, чтобы использовать исключение и таймер
from utils import helpers
try:
    import config
    # Пытаемся получить PROJECT_ROOT из config.py
    if hasattr(config, 'PROJECT_ROOT'):
        PROJECT_ROOT_PATH = config.PROJECT_ROOT
    else:
        # Если в конфиге нет, вычисляем относительно этого файла
        # Предполагаем структуру: project_root/core/odm_runner.py
        PROJECT_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logging.warning(f"Переменная PROJECT_ROOT не найдена в config. Используется расчетный путь: {PROJECT_ROOT_PATH}")
except ImportError:
    # Если конфиг не импортируется, вычисляем относительно этого файла
    PROJECT_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logging.warning(f"Не удалось импортировать config. Используется расчетный путь для PROJECT_ROOT: {PROJECT_ROOT_PATH}")

# Получаем логгер для этого модуля
logger = logging.getLogger(__name__)

def run_odm(image_dir_abs: str, # Абсолютный путь к images на хосте
            output_base_dir_abs: str, # Абсолютный путь к БАЗОВОЙ папке для вывода на хосте (напр., data/output)
            project_name: str = "odm_processing", # Имя папки/проекта ODM для результатов
            odm_options: Optional[Dict[str, Any]] = None,
            run_method: str = 'docker', docker_image: str = 'opendronemap/odm:latest'):
    """
    Запускает OpenDroneMap для обработки изображений, адаптировано под ODM v3.x+
    (использование --project-path и позиционного аргумента для имени проекта).

    Args:
        image_dir_abs: Абсолютный путь к папке с входными изображениями на хост-машине.
                       Ожидается, что эта папка содержит только файлы изображений.
        output_base_dir_abs: Абсолютный путь к папке на хост-машине, внутри которой
                             ODM создаст папку с именем project_name для результатов.
        odm_options: Словарь с дополнительными параметрами для ODM (ключ без '--').
        run_method: 'docker' или 'native'.
        docker_image: Имя Docker образа ODM 'opendronemap/odm:latest'

    Returns:
        True в случае условного успеха запуска ODM (код возврата 0 и папка создана), False иначе.

    Raises:
        helpers.PipelineError: В случае критических ошибок конфигурации или запуска.
        ValueError: Если project_name='images'.
    """
    logger.info(f"--- Запуск OpenDroneMap для проекта '{project_name}' (метод: {run_method}) ---")

    # --- Проверки входных данных ---
    if not os.path.isdir(image_dir_abs):
        logger.error(f"Директория с входными изображениями не найдена: {image_dir_abs}")
        raise helpers.PipelineError(f"Input image directory not found: {image_dir_abs}")
    if not os.listdir(image_dir_abs):
         logger.error(f"Директория с входными изображениями пуста: {image_dir_abs}")
         raise helpers.PipelineError(f"Input image directory is empty: {image_dir_abs}")
    if project_name.lower() == 'images':
         logger.error("Имя проекта ODM ('project_name') не может быть 'images'.")
         raise ValueError("ODM project name cannot be 'images'")

    # Убедимся, что базовая папка вывода существует на хосте
    try:
        os.makedirs(output_base_dir_abs, exist_ok=True)
    except OSError as e:
        logger.error(f"Не удалось создать базовую директорию для вывода ODM: {output_base_dir_abs} - {e}")
        raise helpers.PipelineError(f"Could not create output base directory: {output_base_dir_abs}") from e

    # --- Подготовка команды ---
    cmd = []
    if run_method == 'docker':
        logger.debug(f"Использование Docker образа: {docker_image}")
        cmd = ['docker', 'run', '--rm'] # -it флаги не нужны для неинтерактивного запуска
        # Проверка доступности Docker
        try:
             subprocess.run(['docker', '--version'], check=True, capture_output=True, text=True)
             logger.info("Docker доступен.")
        except (FileNotFoundError, subprocess.CalledProcessError) as docker_e:
             logger.fatal("Docker не найден или не запущен. Установите Docker и запустите его.")
             raise helpers.OdmError("Docker is not available.") from docker_e

        # --- Монтирование томов ---
        # Конвертируем пути для Docker (особенно важно для Windows)
        host_image_dir_docker = image_dir_abs.replace('\\', '/')
        host_output_base_docker = output_base_dir_abs.replace('\\', '/')

        # Монтируем папку с изображениями хоста в /code/images контейнера (read-only)
        cmd.extend(['-v', f'{host_image_dir_docker}:/code/images:ro'])
        logger.info(f"Монтирование тома (вход):  Хост='{image_dir_abs}' -> Контейнер='/code/images'")

        # Монтируем БАЗОВУЮ папку вывода хоста в /code/odm_output контейнера
        cmd.extend(['-v', f'{host_output_base_docker}:/code/odm_output'])
        logger.info(f"Монтирование тома (выход): Хост='{output_base_dir_abs}' -> Контейнер='/code/odm_output'")
        # ----------------------------------------------------

        # --- Обработка GPU ---
        # Используем дефис в ключе 'use-gpu' как в документации ODM
        use_gpu_flag = odm_options and odm_options.get('use-gpu', False)
        if use_gpu_flag:
            logger.info("Запрос использования GPU для ODM в Docker.")
            try:
                 subprocess.run(['nvidia-smi'], check=True, capture_output=True, text=True)
                 cmd.extend(['--gpus', 'all'])
                 logger.info("Добавлен флаг --gpus all.")
            except (FileNotFoundError, subprocess.CalledProcessError):
                 logger.warning("Команда 'nvidia-smi' не найдена или вернула ошибку в WSL. GPU не будет использоваться Docker.")
                 # Не добавляем флаг --gpus all, ODM сам решит (или упадет, если --use-gpu передано ниже)
        # ----------------------------------------------------

        # Имя Docker образа
        cmd.append(docker_image)

        # --- АРГУМЕНТЫ ДЛЯ ODM run.py ---
        # 1. Указываем --project-path ВНУТРИ контейнера, куда ODM будет писать папку project_name
        cmd.extend(['--project-path', '/code/odm_output'])
        logger.info("ODM --project-path (внутри контейнера): /code/odm_output")
        # ODM автоматически найдет изображения в /code/images (стандартное поведение)

        # 2. Добавляем остальные опции ODM из словаря
        if odm_options:
            options_to_add = odm_options.copy()
            # Удаляем опции, которые управляются иначе или могут конфликтовать
            options_to_add.pop('use-gpu', None)
            options_to_add.pop('orthophoto-tif', None) # Устаревший/нераспознанный
            options_to_add.pop('name', None)           # Нераспознанный
            options_to_add.pop('project-name', None)   # Устаревший

            for key, value in options_to_add.items():
                arg_key = f'--{key}'
                # Обработка булевых флагов: ODM ожидает просто флаг без значения
                if isinstance(value, bool):
                    if value: # Добавляем флаг только если он True
                        cmd.append(arg_key)
                    # Если False, просто не добавляем флаг
                elif value is not None: # Добавляем опции со значениями
                    cmd.extend([arg_key, str(value)])

        cmd.append(project_name) 
        logger.info(f"ODM project name (позиционный аргумент): {project_name}")
        # ---------------------------------------------------------

    elif run_method == 'native':
        # --- Логика для нативного запуска (ТРЕБУЕТ АДАПТАЦИИ И ТЕСТИРОВАНИЯ!) ---
        # Необходимо указать правильный путь к run.py
        odm_run_script = '/path/to/your/OpenDroneMap/run.py'
        logger.warning(f"Используется нативный запуск ODM. Убедитесь, что ODM установлен локально и путь '{odm_run_script}' корректен.")
        if not os.path.exists(odm_run_script):
             logger.fatal(f"Скрипт ODM 'run.py' не найден по пути: {odm_run_script}")
             raise helpers.OdmError(f"ODM run script not found: {odm_run_script}")

        cmd = ['python', odm_run_script]
        # Указываем базовую папку, куда ODM будет писать вывод (--project-path)
        # При нативном запуске ODM будет писать в output_base_dir_abs/project_name
        cmd.extend(['--project-path', os.path.abspath(output_base_dir_abs)])

        # Указываем имя проекта
        # Проверить, использует ли нативный run.py флаг --name или позиционный аргумент
        # cmd.extend(['--name', project_name]) # Старый вариант

        # Добавляем опции
        if odm_options:
             options_to_add = odm_options.copy()
             options_to_add.pop('orthophoto-tif', None)
             options_to_add.pop('name', None)
             options_to_add.pop('project-name', None)
             # use-gpu обрабатывается самим run.py при нативной сборке с CUDA
             for key, value in options_to_add.items():
                 arg_key = f'--{key}'
                 if isinstance(value, bool):
                     if value: cmd.append(arg_key)
                 elif value is not None: cmd.extend([arg_key, str(value)])

        # Имя проекта как позиционный аргумент
        cmd.append(project_name)

        # При нативном запуске ODM должен сам найти папку 'images'
        # либо в текущей директории, либо относительно --project-path.
        # Возможно, потребуется запускать main.py из директории, содержащей 'images'.
        logger.warning("Нативный запуск: убедитесь, что ODM может найти папку с изображениями.")
        # -----------------------------------------------------------

    else:
        logger.fatal(f"Неизвестный метод запуска ODM: {run_method}")
        raise ValueError(f"Unsupported ODM run method: {run_method}")

    # Формируем строку для лога
    command_str_log = " ".join(map(shlex.quote, cmd))
    logger.info(f"Итоговая команда запуска ODM:\n{command_str_log}")

    # --- Запуск ODM и логирование вывода ---
    logger.info("Запуск процесса ODM...")
    return_code = -1 # Инициализируем кодом ошибки
    try:
        # Используем Popen для чтения вывода в реальном времени
        # Указываем рабочую директорию как корень проекта для консистентности,
        # особенно если native runner ищет 'images' относительно CWD.
        working_directory = PROJECT_ROOT_PATH if run_method == 'native' else None

        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding='utf-8', errors='replace', # Добавили errors='replace'
                              bufsize=1, universal_newlines=True,
                              cwd=working_directory) as process:
            # Читаем вывод построчно, пока процесс не завершится
            for line in process.stdout:
                if line: # Проверяем, что строка не пустая
                    # Выводим лог ODM с INFO уровнем
                    logger.info(f"[ODM] {line.strip()}")

        return_code = process.returncode # Получаем код возврата после завершения

    except FileNotFoundError as fnf_e:
        cmd_exec = cmd[0]
        logger.fatal(f"Команда '{cmd_exec}' не найдена. Убедитесь, что соответствующее ПО установлено и в PATH. {fnf_e}")
        if cmd_exec == 'docker':
             raise helpers.OdmError("Docker command not found. Is Docker installed and running?") from fnf_e
        else:
             # Для python проверяем путь к odm_run_script
             if cmd_exec == 'python' and len(cmd) > 1 and not os.path.exists(cmd[1]):
                  logger.fatal(f"Скрипт ODM '{cmd[1]}' не найден.")
             raise helpers.OdmError(f"Command '{cmd_exec}' or script not found.") from fnf_e
    except Exception as e:
        logger.error(f"Ошибка при запуске или во время выполнения ODM: {e}", exc_info=True)
        # Передаем исключение выше
        raise helpers.OdmError(f"Failed to run ODM: {e}") from e

    # --- Проверка результата ---
    # Путь к папке, которую должен был создать ODM на хосте
    expected_output_project_path = os.path.join(output_base_dir_abs, project_name)

    if return_code == 0:
        # Проверяем не только код возврата, но и наличие папки результатов
        if os.path.isdir(expected_output_project_path):
            logger.info(f"--- ODM для проекта '{project_name}' завершен успешно ---")
            return True
        else:
            logger.error(f"ODM завершился с кодом 0, но папка результатов не найдена: {expected_output_project_path}")
            # Возможно, ODM записал вывод в другое место? Проверить логи ODM выше.
            raise helpers.OdmError(f"ODM finished with code 0 but output project folder was not found: {expected_output_project_path}")
    else: # return_code != 0
         logger.error(f"--- ODM для проекта '{project_name}' завершен с ошибкой (код: {return_code}) ---")
         # Генерируем исключение для обработки в main.py
         raise helpers.OdmError(f"ODM process for project '{project_name}' finished with error code {return_code}")

    return False
