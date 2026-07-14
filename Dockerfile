FROM python:3.10-slim-bullseye

WORKDIR /app

# Dependências de sistema para pm4py e matplotlib
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    graphviz \
    libgraphviz-dev \
    && rm -rf /var/lib/apt/lists/*

# Usa versões de NumPy/SciPy compatíveis com CPUs antigas
# (wheels do PyPI para Python 3.10 + Bullseye são compilados para x86-64 baseline)
RUN pip install --no-cache-dir \
    numpy==1.24.4 \
    scipy==1.11.4

COPY requirements.txt .

# Instala o restante das dependências (numpy e scipy já instalados acima serão ignorados)
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
