FROM python:3.12-slim
WORKDIR /bot
RUN pip install --no-cache-dir requests
COPY bot.py .
CMD ["python", "-u", "bot.py"]
