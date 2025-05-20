# Выбор базового образа Miniconda3
FROM continuumio/miniconda3:latest

# Установка переменных окружения
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Установка системных зависимостей
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    curl \
    libgl1-mesa-glx
RUN apt-get clean
RUN rm -rf /var/lib/apt/lists/*

# Установка рабочей директории
WORKDIR /app

# Клонирование репозитория
ARG GIT_REPO_URL="https://github.com/ilya-orlov-13/orthophoto.git"
ARG GIT_BRANCH="main"
RUN git clone --branch ${GIT_BRANCH} --depth 1 ${GIT_REPO_URL} .

# Убедимся, что environment.yml существует после клонирования
RUN if [ ! -f environment.yml ]; then \
        echo "ОШИБКА: Файл environment.yml не найден после клонирования репозитория!" >&2; \
        exit 1; \
    fi

# Устанавливаем/обновляем пакеты в базовом окружении из environment.yml
RUN conda env update --name base --file environment.yml && \
    conda clean --all -f -y

RUN echo "Список установленных пакетов (частично):" conda list numpy opencv pillow rasterio matplotlib scipy shapely requests

SHELL ["/opt/conda/bin/bash", "-c"]

RUN echo "Проверка базового окружения:" && \
    python --version && \
    pip --version && \
    conda list

CMD ["python", "main.py"]
