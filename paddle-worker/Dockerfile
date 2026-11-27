FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PORT=7860
WORKDIR /app
RUN python -m pip install --upgrade pip && \
    python -m pip install "paddlepaddle==3.2.2" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ && \
    python -m pip install "paddleocr==3.7.0" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" \
      "python-multipart>=0.0.9" "pillow>=10.3" "numpy>=1.26,<2"
COPY app.py ./app.py
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
