"""
BPMN Model Evaluation Service
Avalia modelos BPMN gerados pelo portal SBMN usando métricas de Process Mining.

Endpoints:
  POST /evaluate/reference-model  — soluções .bpmn + modelo de referência .bpmn
  POST /evaluate/event-log        — soluções .bpmn + log de eventos .xes
  GET  /health                    — health check
"""

import os
import io
import re
import base64
import tempfile
import time
import zipfile
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import pandas as pd
import numpy as np
from scipy.stats import hmean

import pm4py
from pm4py.objects.conversion.bpmn import converter as bpmn_converter
from pm4py.algo.simulation.playout.petri_net import algorithm as simulator
from pm4py.algo.conformance.tokenreplay import algorithm as token_replay
from pm4py.algo.evaluation.precision import algorithm as precision_algo
from pm4py.algo.evaluation.generalization import algorithm as generalization_algo
from pm4py.algo.evaluation.simplicity import algorithm as simplicity_algo

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="BPMN Evaluation Service",
    description="Avalia modelos BPMN gerados a partir de especificações SBMN",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Core evaluation logic
# ---------------------------------------------------------------------------

def evaluate_model(log, petri_net, initial_marking, final_marking):
    """Calcula Recall, Precision, Generalization, Simplicity para um modelo."""
    token_replay_results = token_replay.apply(log, petri_net, initial_marking, final_marking)
    trace_fitnesses = [res["trace_fitness"] for res in token_replay_results]
    recall = sum(trace_fitnesses) / len(trace_fitnesses) if trace_fitnesses else 0.0
    precision = precision_algo.apply(log, petri_net, initial_marking, final_marking)
    generalization = generalization_algo.apply(log, petri_net, initial_marking, final_marking)
    simplicity = simplicity_algo.apply(petri_net)
    return recall, precision, generalization, simplicity


def calculate_harmonic_mean(recall, precision, generalization, simplicity):
    """Calcula a média harmônica das quatro métricas de qualidade."""
    metrics = [recall, precision, generalization, simplicity]
    if all(m > 0 for m in metrics):
        return float(hmean(metrics))
    return 0.0


def abbreviate_model_name(model_name):
    """Abrevia nomes de modelos para uso nos gráficos. Ex: S120_proc_thesisDefense.bpmn -> S120_TDef"""
    if not model_name:
        return "N/A"
    base_name = os.path.splitext(model_name)[0]
    parts = base_name.split('_', 1)
    model_id = parts[0]
    process_part = parts[1] if len(parts) > 1 else ""
    process_part = re.sub(r'^(proc_|process_|modelo_)', '', process_part, flags=re.IGNORECASE)
    tokens = []
    for chunk in re.split(r'[_\-\s]+', process_part):
        if not chunk:
            continue
        camel_tokens = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+', chunk)
        if camel_tokens:
            tokens.extend(camel_tokens)
        else:
            tokens.append(chunk)
    if len(tokens) >= 2:
        process_abbr = f"{tokens[0][0].upper()}{tokens[1][:3].title()}"
    elif len(tokens) == 1:
        process_abbr = tokens[0][:4].title()
    else:
        process_abbr = "Model"
    return f"{model_id}_{process_abbr}"


def load_bpmn_to_petri(bpmn_path: str):
    """Converte arquivo .bpmn em Petri Net."""
    bpmn_graph = pm4py.read_bpmn(bpmn_path)
    net, im, fm = bpmn_converter.apply(
        bpmn_graph, variant=bpmn_converter.Variants.TO_PETRI_NET
    )
    return net, im, fm


def simulate_log_from_bpmn(bpmn_path: str, n_traces: int = 100):
    """Simula log de eventos a partir de um modelo BPMN de referência."""
    net, im, fm = load_bpmn_to_petri(bpmn_path)
    log = simulator.apply(
        net, im,
        variant=simulator.Variants.BASIC_PLAYOUT,
        parameters={"no_traces": n_traces},
    )
    return log


def run_evaluation(log, solution_paths: List[str]):
    """Avalia lista de soluções .bpmn contra um log."""
    results = []
    for path in solution_paths:
        model_name = os.path.basename(path)
        try:
            net, im, fm = load_bpmn_to_petri(path)
            start = time.time()
            recall, precision, generalization, simplicity = evaluate_model(log, net, im, fm)
            elapsed = time.time() - start
            hm = calculate_harmonic_mean(recall, precision, generalization, simplicity)
            results.append({
                "model": model_name,
                "recall": round(recall, 4),
                "precision": round(precision, 4),
                "generalization": round(generalization, 4),
                "simplicity": round(simplicity, 4),
                "harmonic_mean": round(hm, 4),
                "execution_time_s": round(elapsed, 4),
            })
        except Exception as e:
            results.append({
                "model": model_name,
                "error": str(e),
                "recall": None,
                "precision": None,
                "generalization": None,
                "simplicity": None,
                "harmonic_mean": None,
                "execution_time_s": None,
            })
    return results


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

PALETTE = {
    "Recall":         "#2196F3",
    "Precision":      "#FF9800",
    "Generalization": "#4CAF50",
    "Simplicity":     "#9C27B0",
}


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


def plot_metrics_line(results: List[dict]) -> str:
    """Gráfico de linhas por métrica (um subplot por métrica)."""
    metrics = ["Recall", "Precision", "Generalization", "Simplicity"]
    valid = [r for r in results if r.get("recall") is not None]
    if not valid:
        return ""

    indices = list(range(1, len(valid) + 1))
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle("Métricas por Solução", fontsize=14, fontweight="bold", y=1.01)

    for i, metric in enumerate(metrics):
        ax = axes[i // 2][i % 2]
        values = [r[metric.lower()] for r in valid]
        color = PALETTE[metric]
        ax.plot(indices, values, marker="o", linestyle="-", color=color,
                linewidth=2, markersize=5, label=metric)
        ax.set_title(metric, fontsize=11, fontweight="bold")
        ax.set_xlabel("Índice da Solução", fontsize=9)
        ax.set_ylabel("Valor", fontsize=9)
        ax.set_ylim(0, 1.05)
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.tick_params(labelsize=8)
        ax.legend(fontsize=8)

    plt.tight_layout()
    return _fig_to_b64(fig)


def plot_harmonic_mean_line(results: List[dict]) -> str:
    """Gráfico de linha da média harmônica por solução."""
    valid = [r for r in results if r.get("harmonic_mean") is not None]
    if not valid:
        return ""

    indices = list(range(1, len(valid) + 1))
    values = [r["harmonic_mean"] for r in valid]
    best_idx = int(np.argmax(values))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(indices, values, marker="o", linestyle="-", color="#E91E63",
            linewidth=2, markersize=5, label="Harmonic Mean")
    ax.scatter([indices[best_idx]], [values[best_idx]], color="gold",
               s=120, zorder=5, label=f"Best: {values[best_idx]:.4f}")
    ax.set_title("Média Harmônica por Solução", fontsize=13, fontweight="bold")
    ax.set_xlabel("Índice da Solução", fontsize=10)
    ax.set_ylabel("Média Harmônica", fontsize=10)
    ax.set_ylim(0, 1.05)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(fontsize=9)
    plt.tight_layout()
    return _fig_to_b64(fig)


def plot_radar(results: List[dict]) -> str:
    """Radar chart com média de cada métrica."""
    valid = [r for r in results if r.get("recall") is not None]
    if not valid:
        return ""

    metrics = ["Recall", "Precision", "Generalization", "Simplicity"]
    means = [sum(r[m.lower()] for r in valid) / len(valid) for m in metrics]
    means_closed = means + [means[0]]
    angles = [n / float(len(metrics)) * 2 * 3.14159 for n in range(len(metrics))]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    ax.plot(angles, means_closed, "o-", linewidth=2, color="#2196F3")
    ax.fill(angles, means_closed, alpha=0.25, color="#2196F3")
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(metrics, fontsize=11)
    ax.set_ylim(0, 1)
    ax.set_title("Média das Métricas", fontsize=13, fontweight="bold", pad=15)
    ax.grid(True)
    return _fig_to_b64(fig)


def plot_boxplot(results: List[dict]) -> str:
    """Box plot de distribuição de cada métrica."""
    metrics = ["Recall", "Precision", "Generalization", "Simplicity"]
    valid = [r for r in results if r.get("recall") is not None]
    if not valid:
        return ""

    data = {m: [r[m.lower()] for r in valid] for m in metrics}
    df = pd.DataFrame(data)

    fig, axes = plt.subplots(1, 4, figsize=(14, 5), sharey=True)
    fig.suptitle("Distribuição das Métricas", fontsize=13, fontweight="bold")

    for i, metric in enumerate(metrics):
        ax = axes[i]
        color = PALETTE[metric]
        bp = ax.boxplot(df[metric], patch_artist=True, widths=0.5,
                        medianprops={"color": "white", "linewidth": 2})
        bp["boxes"][0].set_facecolor(color)
        bp["boxes"][0].set_alpha(0.7)
        ax.set_title(metric, fontsize=11, fontweight="bold")
        ax.set_ylabel("Valor" if i == 0 else "", fontsize=9)
        ax.set_ylim(0, 1.05)
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.tick_params(labelsize=8)
        ax.set_xticks([])

    plt.tight_layout()
    return _fig_to_b64(fig)


def plot_execution_time(results: List[dict]) -> str:
    """Bar chart com tempo de execução por solução."""
    valid = [r for r in results if r.get("execution_time_s") is not None]
    if not valid:
        return ""

    names = [abbreviate_model_name(r["model"]) for r in valid]
    times = [r["execution_time_s"] for r in valid]

    fig, ax = plt.subplots(figsize=(max(8, len(valid) * 0.8), 4))
    ax.bar(range(len(valid)), times, color="#607D8B", alpha=0.8)
    ax.set_xticks(range(len(valid)))
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Tempo (s)", fontsize=10)
    ax.set_title("Tempo de Avaliação por Solução", fontsize=12, fontweight="bold")
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    plt.tight_layout()
    return _fig_to_b64(fig)


def plot_best_fit_per_process(results: List[dict]) -> str:
    """Bar chart com o melhor modelo (maior média harmônica)."""
    valid = [r for r in results if r.get("harmonic_mean") is not None]
    if not valid:
        return ""

    best = max(valid, key=lambda r: r["harmonic_mean"])
    metrics = ["recall", "precision", "generalization", "simplicity", "harmonic_mean"]
    labels = ["Recall", "Precision", "Generalization", "Simplicity", "Harmonic Mean"]
    values = [best[m] for m in metrics]
    colors = ["#2196F3", "#FF9800", "#4CAF50", "#9C27B0", "#E91E63"]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, values, color=colors, alpha=0.85, edgecolor="black", linewidth=1)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{val:.4f}", ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Valor", fontsize=10)
    ax.set_title(f"Melhor Solução: {abbreviate_model_name(best['model'])}", fontsize=12, fontweight="bold")
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    plt.tight_layout()
    return _fig_to_b64(fig)


def plot_harmonic_mean_avg_vs_best(results: List[dict]) -> str:
    """Bar chart duplo: média harmônica média vs melhor."""
    valid = [r for r in results if r.get("harmonic_mean") is not None]
    if not valid:
        return ""

    hm_values = [r["harmonic_mean"] for r in valid]
    avg_hm = float(np.mean(hm_values))
    best_hm = float(np.max(hm_values))
    best_model = valid[int(np.argmax(hm_values))]["model"]

    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.bar(
        ["Average\nHarmonic Mean", "Best\nHarmonic Mean"],
        [avg_hm, best_hm],
        color=["tab:blue", "tab:orange"],
        alpha=0.85,
        edgecolor="black",
        linewidth=1,
        width=0.4
    )
    for bar, val in zip(bars, [avg_hm, best_hm]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{val:.4f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Harmonic Mean", fontsize=11)
    ax.set_title(f"Average vs Best Harmonic Mean\nBest: {abbreviate_model_name(best_model)}",
                 fontsize=11, fontweight="bold")
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    plt.tight_layout()
    return _fig_to_b64(fig)


# ---------------------------------------------------------------------------
# Statistics and response builder
# ---------------------------------------------------------------------------

def build_statistics(results: List[dict]) -> dict:
    """Calcula estatísticas agregadas das métricas."""
    valid = [r for r in results if r.get("recall") is not None]
    if not valid:
        return {}
    metrics = ["recall", "precision", "generalization", "simplicity", "harmonic_mean"]
    stats = {}
    for m in metrics:
        values = pd.Series([r[m] for r in valid if r.get(m) is not None])
        stats[m] = {
            "mean": round(float(values.mean()), 4),
            "std": round(float(values.std()), 4),
            "min": round(float(values.min()), 4),
            "max": round(float(values.max()), 4),
        }
    return stats


def build_best_result(results: List[dict]) -> dict:
    """Retorna o melhor resultado com base na média harmônica."""
    valid = [r for r in results if r.get("harmonic_mean") is not None]
    if not valid:
        return {}
    return max(valid, key=lambda r: r["harmonic_mean"])


def build_response(results: List[dict], mode: str) -> dict:
    """Monta resposta final com métricas, estatísticas e gráficos."""
    stats = build_statistics(results)
    valid_count = sum(1 for r in results if r.get("recall") is not None)
    error_count = len(results) - valid_count

    return {
        "mode": mode,
        "total_solutions": len(results),
        "evaluated": valid_count,
        "errors": error_count,
        "statistics": stats,
        "best_result": build_best_result(results),
        "results": results,
        "charts": {
            "metrics_line":           plot_metrics_line(results),
            "harmonic_mean_line":     plot_harmonic_mean_line(results),
            "radar":                  plot_radar(results),
            "boxplot":                plot_boxplot(results),
            "execution_time":         plot_execution_time(results),
            "best_fit":               plot_best_fit_per_process(results),
            "avg_vs_best":            plot_harmonic_mean_avg_vs_best(results),
        },
    }


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def is_bpmn_file(filename: str) -> bool:
    return filename.lower().endswith(".bpmn")


def extract_bpmn_from_zip(zip_content: bytes, tmpdir: str) -> List[str]:
    paths = []
    with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            filename = os.path.basename(member.filename)
            if not filename or not is_bpmn_file(filename):
                continue
            dest = os.path.join(tmpdir, filename)
            with zf.open(member) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            paths.append(dest)
    return paths


async def save_upload(file: UploadFile, tmpdir: str):
    dest = os.path.join(tmpdir, os.path.basename(file.filename))
    content = await file.read()
    with open(dest, "wb") as fh:
        fh.write(content)
    return dest, content


async def collect_solution_paths(solutions: List[UploadFile], tmpdir: str) -> List[str]:
    sol_paths = []
    for upload in solutions:
        fname = upload.filename.lower()
        path, content = await save_upload(upload, tmpdir)
        if fname.endswith(".zip"):
            extracted = extract_bpmn_from_zip(content, tmpdir)
            if not extracted:
                raise HTTPException(400, f"O arquivo ZIP '{upload.filename}' não contém nenhum arquivo .bpmn.")
            sol_paths.extend(extracted)
        elif is_bpmn_file(upload.filename):
            sol_paths.append(path)
        else:
            raise HTTPException(400, f"Arquivo '{upload.filename}' não é .bpmn nem .zip.")
    return sol_paths


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "service": "BPMN Evaluation Service", "version": "1.2.0"}


@app.post("/evaluate/reference-model")
async def evaluate_with_reference_model(
    solutions: List[UploadFile] = File(..., description="Soluções .bpmn individuais ou um .zip contendo os .bpmn"),
    reference_model: UploadFile = File(..., description="Modelo de referência .bpmn"),
    n_traces: int = 100,
):
    """
    Avalia modelos BPMN comparando-os com um **modelo de referência** (.bpmn).
    O log de eventos é simulado automaticamente a partir do modelo de referência.
    """
    if not is_bpmn_file(reference_model.filename):
        raise HTTPException(400, "O modelo de referência deve ser um arquivo .bpmn.")

    with tempfile.TemporaryDirectory() as tmpdir:
        ref_path, _ = await save_upload(reference_model, tmpdir)
        sol_paths = await collect_solution_paths(solutions, tmpdir)
        sol_paths = [p for p in sol_paths if os.path.abspath(p) != os.path.abspath(ref_path)]

        if not sol_paths:
            raise HTTPException(400, "Nenhuma solução .bpmn encontrada para avaliar.")

        try:
            log = simulate_log_from_bpmn(ref_path, n_traces=n_traces)
        except Exception as e:
            raise HTTPException(500, f"Erro ao simular log do modelo de referência: {e}")

        results = run_evaluation(log, sorted(sol_paths))

    return JSONResponse(content=build_response(results, mode="reference-model"))


@app.post("/evaluate/event-log")
async def evaluate_with_event_log(
    solutions: List[UploadFile] = File(..., description="Soluções .bpmn individuais ou um .zip contendo os .bpmn"),
    event_log: UploadFile = File(..., description="Log de eventos real .xes"),
):
    """
    Avalia modelos BPMN comparando-os com um **log de eventos real** (.xes).
    """
    if not event_log.filename.lower().endswith(".xes"):
        raise HTTPException(400, "O log de eventos deve ser um arquivo .xes.")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_path, _ = await save_upload(event_log, tmpdir)
        sol_paths = await collect_solution_paths(solutions, tmpdir)

        if not sol_paths:
            raise HTTPException(400, "Nenhuma solução .bpmn encontrada para avaliar.")

        try:
            log = pm4py.read_xes(log_path)
        except Exception as e:
            raise HTTPException(500, f"Erro ao ler arquivo .xes: {e}")

        results = run_evaluation(log, sorted(sol_paths))

    return JSONResponse(content=build_response(results, mode="event-log"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
