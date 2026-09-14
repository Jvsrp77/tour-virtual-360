# Imagem de producao do Tour Virtual.
#
# Os modelos de IA (302 MB) e os dados NAO entram na imagem: sao volumes. Assim
# a imagem fica pequena, atualizar o codigo nao rebaixa nem reenvia os modelos,
# e os tours sobrevivem a troca de versao.
FROM python:3.11-slim

# o opencv-python precisa destas duas mesmo em modo headless
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY static/ ./static/

# o OpenCL e desligado no codigo tambem; aqui e cinto e suspensorio, porque em
# container ele ja travou o processo inteiro durante a costura
ENV OPENCV_OPENCL_RUNTIME=disabled \
    OPENCV_OPENCL_DEVICE=disabled \
    PYTHONUNBUFFERED=1 \
    TOUR_PORTA=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://127.0.0.1:8000/saude || exit 1

CMD ["python", "servidor.py"]
