# 1. Выбор базового образа Miniconda3
FROM continuumio/miniconda3:latest

# 2. Установка переменных окружения
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. Установка системных зависимостей
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    curl \
    # libgl1-mesa-glx # Для OpenCV headless, если используется
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 4. Установка рабочей директории
WORKDIR /app

# 5. Клонирование репозитория
ARG GIT_REPO_URL="https://github.com/ilya-orlov-13/orthophoto.git"
ARG GIT_BRANCH="main"
# Клонируем с --depth 1 для экономии (только последний коммит)
# Точка в конце означает клонировать в текущую WORKDIR (/app)
RUN git clone --branch ${GIT_BRANCH} --depth 1 ${GIT_REPO_URL} .

# 6. Создание Conda-окружения из файла environment.yml
#    Имя окружения будет взято из поля 'name' в environment.yml.
RUN conda env create -f environment.yml && \
    conda clean --all -f -y

# 7. Активация Conda-окружения для последующих команд
ENV CONDA_ENV_NAME ortho_env
SHELL ["conda", "run", "-n", "${CONDA_ENV_NAME}", "/bin/bash", "-c"]

RUN echo "Conda environment $CONDA_ENV_NAME is active." && \
    echo "Python version:" && \
    python --version && \
    echo "Pip version:" && \
    pip --version && \
    echo "Conda packages:" && \
    conda list

# 9. Указание команды, которая будет выполняться при запуске контейнера
CMD ["python", "main.py"]
