# BPMN Evaluation Service

Serviço de avaliação de modelos BPMN gerados a partir de especificações SBMN.
Calcula as métricas clássicas de Process Mining: **Recall (Fitness)**, **Precision**, **Generalization** e **Simplicity**.

---

## Estrutura do projeto

```
bpmn_evaluator/
├── main.py           # Serviço FastAPI (código principal)
├── requirements.txt  # Dependências Python
├── Dockerfile        # Container Docker
└── README.md         # Este arquivo
```

---

## Como rodar

### Opção 1 — Python direto

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Opção 2 — Docker

```bash
docker build -t bpmn-evaluator .
docker run -d -p 8000:8000 --name bpmn-evaluator bpmn-evaluator
```

Acesse a documentação interativa em: **http://localhost:8000/docs**

---

## Endpoints

### `GET /health`
Health check.

```json
{ "status": "ok", "service": "BPMN Evaluation Service" }
```

---

### `POST /evaluate/reference-model`

Avalia soluções BPMN comparando com um **modelo de referência** (.bpmn).
O log de eventos é simulado automaticamente a partir do modelo de referência.

**Form-data:**

| Campo           | Tipo               | Descrição                                      |
|-----------------|--------------------|------------------------------------------------|
| `solutions`     | arquivo(s) `.bpmn` | Soluções geradas (S0, S1, S2...) — múltiplos   |
| `reference_model` | arquivo `.bpmn`  | Modelo de referência (RM)                      |
| `n_traces`      | int (opcional)     | Nº de traços a simular (padrão: 100)           |

**Exemplo com curl:**
```bash
curl -X POST http://localhost:8000/evaluate/reference-model \
  -F "solutions=@S0_proc.bpmn" \
  -F "solutions=@S1_proc.bpmn" \
  -F "solutions=@S2_proc.bpmn" \
  -F "reference_model=@RM_proc.bpmn" \
  -F "n_traces=100"
```

---

### `POST /evaluate/event-log`

Avalia soluções BPMN comparando com um **log de eventos real** (.xes).

**Form-data:**

| Campo       | Tipo               | Descrição                                    |
|-------------|--------------------|----------------------------------------------|
| `solutions` | arquivo(s) `.bpmn` | Soluções geradas (S0, S1, S2...) — múltiplos |
| `event_log` | arquivo `.xes`     | Log de eventos real                          |

**Exemplo com curl:**
```bash
curl -X POST http://localhost:8000/evaluate/event-log \
  -F "solutions=@S0_proc.bpmn" \
  -F "solutions=@S1_proc.bpmn" \
  -F "event_log=@process.xes"
```

---

## Resposta JSON

Ambos os endpoints retornam o mesmo formato:

```json
{
  "mode": "reference-model",
  "total_solutions": 3,
  "evaluated": 3,
  "errors": 0,
  "statistics": {
    "recall":         { "mean": 0.92, "std": 0.03, "min": 0.89, "max": 0.95 },
    "precision":      { "mean": 0.88, "std": 0.05, "min": 0.83, "max": 0.93 },
    "generalization": { "mean": 0.94, "std": 0.02, "min": 0.92, "max": 0.96 },
    "simplicity":     { "mean": 0.91, "std": 0.04, "min": 0.87, "max": 0.95 }
  },
  "results": [
    {
      "model": "S0_proc.bpmn",
      "recall": 0.9312,
      "precision": 0.8754,
      "generalization": 0.9421,
      "simplicity": 0.9108,
      "execution_time_s": 0.234
    }
  ],
  "charts": {
    "metrics_line":   "<base64 PNG>",
    "radar":          "<base64 PNG>",
    "boxplot":        "<base64 PNG>",
    "execution_time": "<base64 PNG>"
  }
}
```

### Exibindo os gráficos no portal (JavaScript)

```javascript
const img = document.createElement('img');
img.src = `data:image/png;base64,${response.charts.metrics_line}`;
document.getElementById('chart-container').appendChild(img);
```

---

## Integração com o portal (exemplo JavaScript/fetch)

```javascript
async function evaluateWithReferenceModel(solutionFiles, referenceFile) {
  const formData = new FormData();

  // Adiciona cada solução .bpmn
  solutionFiles.forEach(file => {
    formData.append('solutions', file);
  });

  // Adiciona o modelo de referência
  formData.append('reference_model', referenceFile);
  formData.append('n_traces', '100');

  const response = await fetch('http://SEU_SERVIDOR:8000/evaluate/reference-model', {
    method: 'POST',
    body: formData,
  });

  const data = await response.json();
  return data;
}

async function evaluateWithEventLog(solutionFiles, xesFile) {
  const formData = new FormData();

  solutionFiles.forEach(file => {
    formData.append('solutions', file);
  });
  formData.append('event_log', xesFile);

  const response = await fetch('http://SEU_SERVIDOR:8000/evaluate/event-log', {
    method: 'POST',
    body: formData,
  });

  return await response.json();
}
```

---

## Gráficos gerados

| Gráfico          | Chave JSON        | Descrição                                          |
|------------------|-------------------|----------------------------------------------------|
| Linhas por métrica | `metrics_line`  | Evolução de cada métrica ao longo das soluções     |
| Radar            | `radar`           | Média das 4 métricas em gráfico de aranha          |
| Box plot         | `boxplot`         | Distribuição e variação de cada métrica            |
| Tempo            | `execution_time`  | Tempo de avaliação por solução                     |

---

## Métricas calculadas

| Métrica         | Descrição                                                                  |
|-----------------|----------------------------------------------------------------------------|
| **Recall**      | Quão bem o modelo reproduz os comportamentos do log de referência          |
| **Precision**   | Quão específico é o modelo (evita comportamentos não presentes no log)     |
| **Generalization** | Capacidade do modelo de generalizar além dos traços do log              |
| **Simplicity**  | Simplicidade estrutural do modelo (menos elementos = maior simplicidade)   |

---

## Compatibilidade

- Python 3.10+
- pm4py 2.7+
- FastAPI 0.111+
