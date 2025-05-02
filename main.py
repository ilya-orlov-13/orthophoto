import os
import time
import logging
import numpy as np

import json # Нужен для сохранения/загрузки результатов анализа и разметки
import subprocess # Нужен для проверки Docker/nvidia-smi
from typing import Optional, Dict, Any, List # Добавили импорты типов
import shutil # Для копирования/перемещения файлов ODM

# Импортируем конфигурацию и модули
import config # Загружаем наш config.py
# Основные рабочие модули для этого пайплайна:
from core import io_utils, analysis, odm_runner
# Вспомогательные функции и логгер:
from utils import helpers

# --- Глобальная настройка логгера ---
# Определяем абсолютный путь к папке вывода для лог-файла
try:
    # Вычисляем абсолютный путь к папке вывода из конфига
    # Папка 'data/output' внутри корня проекта
    abs_output_dir_for_log_and_analysis = os.path.join(config.PROJECT_ROOT, config.OUTPUT_DIR_REL)
    helpers.setup_logging(
        level=config.LOGGING_LEVEL,
        log_to_file=config.LOG_TO_FILE,
        log_filename=config.LOG_FILENAME,
        output_dir=abs_output_dir_for_log_and_analysis # Передаем абсолютный путь
    )
except Exception as log_e:
     # Используем print, так как логгер мог не инициализироваться
     print(f"FATAL: Failed to setup logging - {log_e}", file=sys.stderr)
     import sys
     sys.exit(1) # Завершаемся, если логгер не настроен

# Получаем логгер для этого модуля ПОСЛЕ настройки
logger = logging.getLogger(__name__)

# --- Вспомогательные функции ---

def run_analysis(orthophoto_path: str, output_dir: str) -> Optional[List[Dict[str, Any]]]:
    """
    Запускает этап анализа парковочных мест

    Args:
        orthophoto_path: Абсолютный путь к итоговому ортофотоплану.
        output_dir: Абсолютный путь к папке для сохранения результатов анализа.

    Returns:
        Список словарей с результатами анализа или None в случае ошибки/пропуска.
    """
    if not config.RUN_PARKING_ANALYSIS:
        logger.info("Анализ парковочных мест отключен в конфигурации.")
        return None # Возвращаем None, если анализ не запускался

    logger.info("--- Этап: Анализ парковочных мест ---")
    analysis_results = [] # Инициализируем пустым списком
    # Используем таймер из helpers
    with helpers.Timer("Анализ парковочных мест"):
        model = None
        slot_definitions = None
        try:
            # --- Загрузка модели ---
            model_dir_abs = os.path.join(config.PROJECT_ROOT, config.MODELS_DIR_REL)
            model_filename = config.PARKING_ANALYSIS_PARAMS.get('model_filename')
            if model_filename:
                # analysis.load_parking_model должен вернуть None при ошибке
                model = analysis.load_parking_model(model_dir_abs, model_filename)
            else:
                logger.warning("Имя файла модели не указано в config.PARKING_ANALYSIS_PARAMS.")

            # --- Загрузка разметки слотов ---
            layout_dir_abs = os.path.join(config.PROJECT_ROOT, config.PARKING_LAYOUT_DIR_REL)
            slot_filename = config.PARKING_ANALYSIS_PARAMS.get('slot_filename')
            if slot_filename:
                slots_path_abs = os.path.join(layout_dir_abs, slot_filename)
                # io_utils.load_json должен вернуть None при ошибке
                slot_definitions = io_utils.load_json(slots_path_abs)
                if slot_definitions is not None and not isinstance(slot_definitions, list):
                     logger.error(f"Файл разметки '{slots_path_abs}' должен содержать список JSON объектов.")
                     slot_definitions = None # Считаем невалидным
            else:
                logger.warning("Имя файла разметки слотов не указано в config.PARKING_ANALYSIS_PARAMS.")

            # --- Выполнение анализа ---
            if model and slot_definitions and os.path.exists(orthophoto_path):
                logger.info("Запуск основного алгоритма анализа...")
                # В analysis.py нужно реализовать логику анализа
                # Эта функция должна вернуть список или None/пустой список при ошибке
                analysis_results = analysis.analyze_parking_slots(
                    orthophoto_path=orthophoto_path,
                    model=model,
                    slot_definitions=slot_definitions,
                    confidence_threshold=config.PARKING_ANALYSIS_PARAMS.get('confidence_threshold', 0.7)
                    # Можно передать и другие параметры из PARKING_ANALYSIS_PARAMS
                )
                if analysis_results is None: analysis_results = [] # Гарантируем список
                logger.info(f"Анализ завершен. Определен статус для {len(analysis_results)} слотов.")
            elif not os.path.exists(orthophoto_path):
                 logger.error(f"Ортофотоплан не найден для анализа: {orthophoto_path}")
            else:
                logger.warning("Пропуск анализа парковок: модель или разметка слотов не загружены/не найдены.")

            # --- Сохранение результатов анализа ---
            if analysis_results: # Сохраняем, даже если пустой список (но анализ запускался)
                # Сохраняем в основную папку вывода output_dir
                results_path_abs = os.path.join(output_dir, config.ANALYSIS_RESULTS_FILENAME)
                io_utils.save_json(analysis_results, results_path_abs)

        except KeyError as ke:
             logger.error(f"Отсутствует необходимый параметр в config.PARKING_ANALYSIS_PARAMS: {ke}")
        except helpers.AnalysisError as ae: # Ловим специфичное исключение анализа
             logger.error(f"Ошибка во время анализа: {ae}", exc_info=True)
        except Exception as analysis_e:
             logger.error(f"Непредвиденная ошибка во время анализа парковок: {analysis_e}", exc_info=True)

    return analysis_results # Возвращаем результаты (может быть пустым списком или None)

def generate_report(stats: dict, output_dir: str):
    """
    (Опционально) Генерирует текстовый отчет с использованием LLM.

    Args:
        stats: Словарь со статистикой выполнения пайплайна.
        output_dir: Абсолютный путь к папке для сохранения отчета.
    """
    if not config.USE_LLM_ASSISTANT:
        logger.info("Генерация отчета LLM отключена в конфигурации.")
        return

    logger.info("--- Этап: Генерация текстового отчета ---")
    # Используем таймер из helpers
    with helpers.Timer("Генерация отчета LLM"):
        try:
            # Импортируем клиент LLM только если он нужен
            from utils import llm_client # Предполагаем, что модуль utils/llm_client.py создан

            # Формируем промпт
            report_prompt = f"""
            Напиши краткий отчет о создании ортофотоплана и анализе парковки на основе следующих данных:
            - Обработано изображений: {stats.get('image_count', 'N/A')}
            - Итоговое разрешение ODM: {stats.get('odm_resolution', 'N/A')} см/пиксель
            - Найден ортофотоплан: {'Да' if stats.get('ortho_found') else 'Нет'}
            - Найден DSM: {'Да' if stats.get('dsm_found') else 'Нет'}
            - Выполнен анализ парковок: {'Да' if stats.get('analysis_run') else 'Нет'}
            """
            analysis_res = stats.get('analysis_results') # Получаем результаты анализа
            if analysis_res is not None: # Проверяем, что ключ существует (даже если список пуст)
                 num_occupied = sum(1 for r in analysis_res if r.get('status') == 'occupied')
                 num_vacant = sum(1 for r in analysis_res if r.get('status') == 'vacant')
                 num_analyzed = len(analysis_res)
                 report_prompt += f"- Результаты анализа ({num_analyzed} слотов): {num_occupied} занято, {num_vacant} свободно.\n"
            report_prompt += f"- Общее время обработки: {helpers.format_time(stats.get('total_time', 0))}\n"
            report_prompt += "\nОтчет должен быть лаконичным, в 3-4 предложениях."

            # Генерируем текст
            # llm_client.generate_text_lmstudio должен быть реализован
            report_text = llm_client.generate_text_lmstudio(
                prompt=report_prompt,
                max_tokens=config.LLM_REPORT_PARAMS.get('max_tokens', 300),
                temperature=config.LLM_REPORT_PARAMS.get('temperature', 0.6),
                api_base=config.LM_STUDIO_API_BASE,
                model_name=config.LM_STUDIO_MODEL_NAME
            )

            # Сохраняем отчет
            if report_text:
                report_path_abs = os.path.join(output_dir, config.REPORT_FILENAME)
                try:
                    with open(report_path_abs, 'w', encoding='utf-8') as f:
                        f.write(f"--- Отчет о выполнении ---\n")
                        f.write(f"Время генерации: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        f.write(report_text)
                    logger.info(f"Текстовый отчет сохранен в: {report_path_abs}")
                except Exception as e:
                    logger.error(f"Не удалось сохранить отчет LLM: {e}")
            else:
                logger.warning("Не удалось сгенерировать текстовый отчет LLM.")

        except ImportError:
             logger.warning("Модуль 'utils.llm_client' не найден или не реализован. Генерация отчета LLM невозможна.")
        except Exception as llm_e:
             logger.error(f"Ошибка при генерации отчета LLM: {llm_e}", exc_info=True)


# --- Основной Пайплайн ---

def main_pipeline():
    """ Основной пайплайн обработки. """
    global_start_time = time.time()
    logger.info("=" * 60)
    logger.info("=== ЗАПУСК ПАЙПЛАЙНА СОЗДАНИЯ ОРТОФОТОПЛАНА (ODM) И АНАЛИЗА ===")
    logger.info("=" * 60)

    # --- Определяем абсолютные пути ---
    try:
        # Абсолютный путь к корневой папке проекта
        project_root_abs = config.PROJECT_ROOT
        # Абсолютный путь к папке с входными изображениями (например, project_root/images)
        input_dir_abs = os.path.join(project_root_abs, config.INPUT_IMAGE_DIR_REL)
        # Абсолютный путь к папке для вывода результатов анализа и логов (например, project_root/data/output)
        output_analysis_dir_abs = os.path.join(project_root_abs, config.OUTPUT_DIR_REL)
        os.makedirs(output_analysis_dir_abs, exist_ok=True) # Создаем папку вывода анализа/логов
        # Путь к папке, ГДЕ ODM создаст папку проекта (в соответствии с простым вариантом README ODM - это корень проекта)
        odm_output_base_dir_on_host = project_root_abs
    except AttributeError as attr_e:
         logger.fatal(f"Ошибка доступа к настройкам путей в config.py: {attr_e}. Убедитесь, что переменные определены.")
         return
    except Exception as path_e:
         logger.fatal(f"Ошибка определения путей проекта: {path_e}.")
         return

    # Собираем статистику для отчета
    pipeline_stats = {"start_time": global_start_time}

    # --- Проверка входных данных ---
    input_images = io_utils.list_images(input_dir_abs)
    pipeline_stats["image_count"] = len(input_images)
    if not input_images:
        logger.fatal(f"Входные изображения не найдены в '{input_dir_abs}'. Завершение работы.")
        return

    # --- Шаг 1: Запуск ODM ---
    # Папка, которую создаст ODM внутри odm_output_base_dir_on_host
    odm_project_output_path_on_host = os.path.join(odm_output_base_dir_on_host, config.ODM_PROJECT_NAME)
    odm_success = False
    try:
        with helpers.Timer("Выполнение OpenDroneMap"):
            odm_success = odm_runner.run_odm(
                image_dir_abs=input_dir_abs,
                output_base_dir_abs=output_analysis_dir_abs,
                project_name=config.ODM_PROJECT_NAME,
                odm_options=config.ODM_OPTIONS,
                run_method=config.ODM_RUN_METHOD,
                docker_image=config.ODM_DOCKER_IMAGE
                # image_dir_abs и output_base_dir_abs больше не нужны как аргументы для этой версии run_odm
            )
    except helpers.OdmError as odm_e:
         logger.fatal(f"Критическая ошибка ODM: {odm_e}")
         return # Завершаем пайплайн
    except Exception as e:
         logger.fatal(f"Непредвиденная ошибка при запуске ODM: {e}", exc_info=True)
         return

    if not odm_success:
        logger.fatal("ODM завершился неудачно. Дальнейшая обработка невозможна.")
        return

    # --- Шаг 2: Поиск результатов ODM ---
    logger.info(f"Поиск результатов ODM в папке: {odm_project_output_path_on_host}")
    # Ищем результаты в папке, которую должен был создать ODM
    orthophoto_path_odm, dsm_path_odm = io_utils.find_odm_results(odm_project_output_path_on_host)

    pipeline_stats["ortho_found"] = bool(orthophoto_path_odm)
    pipeline_stats["dsm_found"] = bool(dsm_path_odm)
    pipeline_stats["odm_resolution"] = config.ODM_OPTIONS.get("orthophoto-resolution", "N/A")

    # Путь к ортофото для передачи в анализ (может быть None)
    final_ortho_path_for_analysis = None

    if orthophoto_path_odm:
         # Опционально: Копируем ортофото в папку output_analysis_dir_abs для удобства
         try:
             # Формируем имя файла в папке вывода анализа
             final_ortho_filename = config.OUTPUT_FILENAME + ".tif"
             destination_path = os.path.join(output_analysis_dir_abs, final_ortho_filename)
             logger.info(f"Копирование ортофотоплана из '{orthophoto_path_odm}' в '{destination_path}'...")
             shutil.copyfile(orthophoto_path_odm, destination_path)
             logger.info(f"Ортофотоплан скопирован успешно.")
             final_ortho_path_for_analysis = destination_path # Используем скопированный путь
         except Exception as copy_e:
              logger.warning(f"Не удалось скопировать ортофотоплан: {copy_e}. "
                             f"Анализ будет использовать исходный путь ODM: {orthophoto_path_odm}")
              final_ortho_path_for_analysis = orthophoto_path_odm # Используем исходный путь
    else:
         logger.error("Не удалось найти итоговый ортофотоплан ODM. Анализ парковок невозможен.")


    # --- Шаг 3: Анализ парковочных мест ---
    analysis_results = None
    if final_ortho_path_for_analysis and os.path.exists(final_ortho_path_for_analysis):
        # Запускаем анализ, передаем папку для сохранения JSON результатов
        analysis_results = run_analysis(final_ortho_path_for_analysis, output_analysis_dir_abs)
        pipeline_stats["analysis_run"] = True
        pipeline_stats["analysis_results"] = analysis_results if analysis_results is not None else []
    else:
         logger.info("Пропуск анализа парковочных мест, так как ортофотоплан недоступен.")
         pipeline_stats["analysis_run"] = False
         pipeline_stats["analysis_results"] = None


    # --- Завершение пайплайна ---
    global_end_time = time.time()
    total_time = global_end_time - global_start_time
    pipeline_stats["total_time"] = total_time

    # --- Шаг 4: Генерация отчета (Опционально) ---
    # Передаем папку для сохранения текстового отчета
    generate_report(pipeline_stats, output_analysis_dir_abs)

    logger.info("=" * 60)
    logger.info(f"=== ПАЙПЛАЙН ЗАВЕРШЕН за {helpers.format_time(total_time)} ===")
    logger.info(f"Результаты ODM находятся в: {odm_project_output_path_on_host}")
    logger.info(f"Результаты анализа и логи находятся в: {output_analysis_dir_abs}")
    logger.info("=" * 60)


# --- Точка входа ---
if __name__ == "__main__":
    logger.info("--- Инициализация Оркестратора ---")
    logger.info(f"Корневая папка проекта: '{config.PROJECT_ROOT}'")
    # Вычисляем абсолютные пути для вывода в консоль
    abs_input_dir = os.path.join(config.PROJECT_ROOT, config.INPUT_IMAGE_DIR_REL)
    abs_output_analysis_dir = os.path.join(config.PROJECT_ROOT, config.OUTPUT_DIR_REL)
    logger.info(f"Каталог входа ('images'): '{abs_input_dir}'")
    logger.info(f"Каталог выхода (анализ, логи): '{abs_output_analysis_dir}'")
    logger.info("-" * 40)

    # Проверка Docker перед запуском (если используется)
    if config.ODM_RUN_METHOD == 'docker':
        logger.info("Проверка доступности Docker...")
        try:
            subprocess.run(['docker', '--version'], check=True, capture_output=True, text=True)
            logger.info("Docker найден и доступен.")
        except (FileNotFoundError, subprocess.CalledProcessError) as docker_err:
            logger.error(f"Docker не найден или не отвечает: {docker_err}. "
                         f"Убедитесь, что Docker установлен, запущен и доступен из этой среды (WSL).")
            exit(1) # Завершаем, если Docker недоступен, но выбран
        except Exception as docker_e:
             logger.error(f"Непредвиденная ошибка при проверке Docker: {docker_e}")
             # Не завершаем, но предупреждаем

    # Проверка наличия входных изображений
    if not io_utils.list_images(abs_input_dir):
        logger.error(f"!!! Входные изображения не найдены в '{abs_input_dir}'. Пожалуйста, добавьте изображения в папку 'images' и перезапустите. !!!")
    else:
        logger.info("Запуск основного пайплайна обработки...")
        try:
            main_pipeline() # Запускаем основной пайплайн
        except helpers.PipelineError as pe: # Ловим наши кастомные ошибки
             logger.critical(f"Критическая ошибка пайплайна: {pe}", exc_info=False)
        except Exception as e: # Ловим все остальные непредвиденные ошибки
             logger.critical(f"Необработанная фатальная ошибка в main: {e}", exc_info=True)

    logger.info("--- Завершение работы программы ---")
