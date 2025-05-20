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
    # libgl1-mesa-glx # Для OpenCV headless, если используется
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Установка рабочей директории
WORKDIR /app

# Клонирование репозитория
ARG GIT_REPO_URL="https://github.com/ilya-orlov-13/orthophoto.git"
ARG GIT_BRANCH="main"
# Клонируем с --depth 1 для экономии (только последний коммит)
# Точка в конце означает клонировать в текущую WORKDIR (/app)
RUN git clone --branch ${GIT_BRANCH} --depth 1 ${GIT_REPO_URL} .

RUN conda install --yes --file <(grep -E -v '^name:|^prefix:|^channels:|^pip:' environment.yml | sed -e '/^dependencies:/d' -e 's/- //g') && \
    conda run pip install -r <(grep -A 1000 -e "^  pip:" environment.yml | grep -e "^  - " | sed -e 's/^  - //') && \
    conda clean --all -f -y

RUN echo "Проверка базового окружения:" && \
    python --version && \
    pip --version && \
    conda list\
    
COPY . .

# Указание команды, которая будет выполняться при запуске контейнера
CMD ["python", "main.py"]
