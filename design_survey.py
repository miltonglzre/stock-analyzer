"""
design_survey.py — Cuestionario interactivo de diseño para el Stock Analyzer.
Corre con: streamlit run design_survey.py
Guarda las respuestas en data/design_survey.json
"""

import streamlit as st
import json
from pathlib import Path

st.set_page_config(
    page_title="Cuestionario de Diseño",
    page_icon="🎨",
    layout="centered",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #080b10; }
[data-testid="stSidebar"] { display: none; }

h1 { color: #00d4aa; }
h3 { color: #e0e0e0; margin-top: 2rem; }

div[data-testid="stRadio"] label,
div[data-testid="stCheckbox"] label {
    font-size: 1rem !important;
    color: #ccc !important;
    cursor: pointer;
}
div[data-testid="stRadio"] > div,
div[data-testid="stCheckbox"] > div {
    background: #111418;
    border: 1px solid #1e2330;
    border-radius: 10px;
    padding: 10px 16px;
    margin-bottom: 6px;
    transition: border-color 0.15s;
}
div[data-testid="stRadio"] > div:hover,
div[data-testid="stCheckbox"] > div:hover {
    border-color: #00d4aa55;
}

.section-label {
    background: linear-gradient(90deg, #00d4aa18, transparent);
    border-left: 3px solid #00d4aa;
    padding: 6px 14px;
    border-radius: 0 8px 8px 0;
    margin: 24px 0 16px 0;
    font-size: 0.9rem;
    font-weight: 700;
    color: #00d4aa;
    letter-spacing: 0.5px;
}
.progress-bar {
    background: #1e2330;
    border-radius: 20px;
    height: 6px;
    margin: 12px 0 24px 0;
}
.progress-fill {
    background: linear-gradient(90deg, #00d4aa, #00ff88);
    border-radius: 20px;
    height: 6px;
    transition: width 0.3s;
}
.saved-box {
    background: #0d3d2e;
    border: 1px solid #00d4aa;
    border-radius: 10px;
    padding: 16px 20px;
    text-align: center;
    margin-top: 20px;
}
</style>
""", unsafe_allow_html=True)

SAVE_PATH = Path(__file__).parent / "data" / "design_survey.json"
SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Load existing answers ──────────────────────────────────────────────────────
def load_answers() -> dict:
    try:
        return json.loads(SAVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_answers(data: dict):
    SAVE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

existing = load_answers()

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("# 🎨 Cuestionario de Diseño")
st.markdown("Responde las preguntas con clicks. Tus respuestas se guardan automáticamente.")

# Progress tracking
if "answers" not in st.session_state:
    st.session_state.answers = existing.copy()

answers = st.session_state.answers
TOTAL_Q = 15
answered = sum(1 for k in answers if answers[k] not in (None, [], ""))
pct = int(answered / TOTAL_Q * 100)

st.markdown(
    f"<div class='progress-bar'>"
    f"<div class='progress-fill' style='width:{pct}%;'></div>"
    f"</div>"
    f"<div style='color:#666;font-size:0.8rem;text-align:right;margin-top:-18px;margin-bottom:20px;'>"
    f"{answered}/{TOTAL_Q} respondidas</div>",
    unsafe_allow_html=True,
)

# ── Section 1: Visual Style ────────────────────────────────────────────────────
st.markdown("<div class='section-label'>SECCIÓN 1 — Estilo Visual</div>", unsafe_allow_html=True)

q1 = st.radio(
    "**1.** ¿Cuál de estos estilos se acerca más a lo que imaginas?",
    options=[
        "A) Dashboard oscuro profesional — Bloomberg / trading terminal (denso, datos en primer plano)",
        "B) App SaaS moderna — tarjetas limpias, gradientes suaves, mucho espacio",
        "C) Fintech/crypto — neón, animaciones, estilo Binance / Robinhood",
        "D) Otro (escribe abajo)",
    ],
    index=["A)", "B)", "C)", "D)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)"] if answers.get("q1","").startswith(o)), "A)")
    ) if answers.get("q1") else 0,
    key="q1_radio",
)
answers["q1"] = q1

if q1.startswith("D)"):
    q1_otro = st.text_input("Descríbelo:", value=answers.get("q1_otro", ""), key="q1_otro_input")
    answers["q1_otro"] = q1_otro

st.divider()

q2 = st.text_input(
    "**2.** ¿Tienes alguna app o sitio web que te guste visualmente? (nombre o URL — opcional)",
    value=answers.get("q2", ""),
    placeholder="Ej: Robinhood, TradingView, Binance, Linear.app...",
    key="q2_input",
)
answers["q2"] = q2

st.divider()

q3 = st.radio(
    "**3.** Para el fondo principal, ¿prefieres?",
    options=[
        "A) Negro muy oscuro (como ahora — #080b10)",
        "B) Gris oscuro suave (#13161c)",
        "C) Azul marino oscuro (#0a0e1a — estilo fintech)",
        "D) Otro",
    ],
    index=["A)", "B)", "C)", "D)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)"] if answers.get("q3","").startswith(o)), "A)")
    ) if answers.get("q3") else 0,
    key="q3_radio",
)
answers["q3"] = q3

st.divider()

q4 = st.radio(
    "**4.** El color de acento verde (#00d4aa) — ¿qué haces con él?",
    options=[
        "A) Me gusta, mantenlo",
        "B) Quiero algo más vibrante (verde eléctrico, cyan)",
        "C) Prefiero azul eléctrico (#4f9cf9)",
        "D) Prefiero violeta/púrpura (#9b59b6)",
        "E) Otro color",
    ],
    index=["A)", "B)", "C)", "D)", "E)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)", "E)"] if answers.get("q4","").startswith(o)), "A)")
    ) if answers.get("q4") else 0,
    key="q4_radio",
)
answers["q4"] = q4

# ── Section 2: Structure ───────────────────────────────────────────────────────
st.markdown("<div class='section-label'>SECCIÓN 2 — Estructura y Navegación</div>", unsafe_allow_html=True)

q5 = st.radio(
    "**5.** La navegación actual tiene tabs arriba. ¿Prefieres?",
    options=[
        "A) Sidebar vertical siempre visible (a la izquierda)",
        "B) Tabs arriba pero más grandes y visuales",
        "C) Una sola página con scroll (sin tabs)",
        "D) Quedarme con tabs pero mejoradas visualmente",
    ],
    index=["A)", "B)", "C)", "D)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)"] if answers.get("q5","").startswith(o)), "A)")
    ) if answers.get("q5") else 0,
    key="q5_radio",
)
answers["q5"] = q5

st.divider()

q6 = st.radio(
    "**6.** ¿Quieres una pantalla de inicio tipo 'Home' con resumen de todo?",
    options=[
        "A) Sí — quiero ver un resumen rápido al abrir la app",
        "B) No — prefiero ir directo al scanner",
        "C) Sí, pero que el scanner sea el home",
    ],
    index=["A)", "B)", "C)"].index(
        next((o[:2] for o in ["A)", "B)", "C)"] if answers.get("q6","").startswith(o)), "A)")
    ) if answers.get("q6") else 0,
    key="q6_radio",
)
answers["q6"] = q6

st.divider()

q7 = st.radio(
    "**7.** ¿Cuál sección usas más día a día?",
    options=[
        "A) Scanner (top buys, conviction picks, explosive movers)",
        "B) Análisis individual de una acción",
        "C) Mis Trades",
        "D) Learning System",
        "E) Todas por igual",
    ],
    index=["A)", "B)", "C)", "D)", "E)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)", "E)"] if answers.get("q7","").startswith(o)), "A)")
    ) if answers.get("q7") else 0,
    key="q7_radio",
)
answers["q7"] = q7

# ── Section 3: Components ──────────────────────────────────────────────────────
st.markdown("<div class='section-label'>SECCIÓN 3 — Componentes Específicos</div>", unsafe_allow_html=True)

q8 = st.radio(
    "**8.** Las tarjetas de 'Top 5 Conviction Picks' — ¿cómo las quieres?",
    options=[
        "A) Más grandes y visuales — que dominen la pantalla",
        "B) Compactas como ahora pero más pulidas",
        "C) En formato de lista horizontal con más detalle",
        "D) Con mini-gráfica de precio dentro de cada tarjeta",
    ],
    index=["A)", "B)", "C)", "D)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)"] if answers.get("q8","").startswith(o)), "A)")
    ) if answers.get("q8") else 0,
    key="q8_radio",
)
answers["q8"] = q8

st.divider()

q9 = st.radio(
    "**9.** ¿Más gráficas o más tablas?",
    options=[
        "A) Más gráficas — que todo sea visual",
        "B) Balance: gráficas para lo importante, tablas para detalles",
        "C) Las tablas me sirven, no cambiar mucho eso",
    ],
    index=["A)", "B)", "C)"].index(
        next((o[:2] for o in ["A)", "B)", "C)"] if answers.get("q9","").startswith(o)), "A)")
    ) if answers.get("q9") else 0,
    key="q9_radio",
)
answers["q9"] = q9

st.divider()

q10 = st.radio(
    "**10.** El Fear & Greed Index — ¿cómo quieres que se vea?",
    options=[
        "A) Gauge circular grande (tipo velocímetro) — muy visual",
        "B) Barra horizontal con el número — como está ahora",
        "C) Solo el número y color — minimalista",
        "D) Que ocupe una sección propia con histórico",
    ],
    index=["A)", "B)", "C)", "D)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)"] if answers.get("q10","").startswith(o)), "A)")
    ) if answers.get("q10") else 0,
    key="q10_radio",
)
answers["q10"] = q10

st.divider()

q11 = st.radio(
    "**11.** ¿Te gustaría un ticker de precios en tiempo real (números que se mueven)?",
    options=[
        "A) Sí — que se actualice automáticamente cada cierto tiempo",
        "B) No — prefiero actualizar manual con el botón de scan",
        "C) Solo para las conviction picks, no para todo",
    ],
    index=["A)", "B)", "C)"].index(
        next((o[:2] for o in ["A)", "B)", "C)"] if answers.get("q11","").startswith(o)), "A)")
    ) if answers.get("q11") else 0,
    key="q11_radio",
)
answers["q11"] = q11

# ── Section 4: Life & Interactivity ───────────────────────────────────────────
st.markdown("<div class='section-label'>SECCIÓN 4 — 'Más Vida' e Interactividad</div>", unsafe_allow_html=True)

st.markdown("**12.** ¿Qué significa 'más vida' para ti? (puedes marcar varias)")
q12_a = st.checkbox("A) Animaciones y transiciones al cargar datos", value=answers.get("q12_a", False), key="q12_a")
q12_b = st.checkbox("B) Colores más vibrantes, menos gris apagado", value=answers.get("q12_b", False), key="q12_b")
q12_c = st.checkbox("C) Más interactivo — hovers, efectos en botones", value=answers.get("q12_c", False), key="q12_c")
q12_d = st.checkbox("D) Más íconos y elementos visuales, menos texto plano", value=answers.get("q12_d", False), key="q12_d")
q12_e = st.checkbox("E) Números con color dinámico (verde/rojo según movimiento)", value=answers.get("q12_e", False), key="q12_e")
q12_f = st.checkbox("F) Tipografía más grande y jerarquía visual clara", value=answers.get("q12_f", False), key="q12_f")
q12_g = st.checkbox("G) Fondos con gradientes / profundidad visual", value=answers.get("q12_g", False), key="q12_g")
answers.update({"q12_a": q12_a, "q12_b": q12_b, "q12_c": q12_c,
                "q12_d": q12_d, "q12_e": q12_e, "q12_f": q12_f, "q12_g": q12_g})

st.divider()

q13 = st.radio(
    "**13.** ¿Quieres alertas visuales dentro de la app cuando una pick llega al target?",
    options=[
        "A) Sí — un banner / notificación prominente",
        "B) Solo un indicador discreto en la tarjeta",
        "C) No es necesario",
    ],
    index=["A)", "B)", "C)"].index(
        next((o[:2] for o in ["A)", "B)", "C)"] if answers.get("q13","").startswith(o)), "A)")
    ) if answers.get("q13") else 0,
    key="q13_radio",
)
answers["q13"] = q13

# ── Section 5: Device & Usage ─────────────────────────────────────────────────
st.markdown("<div class='section-label'>SECCIÓN 5 — Dispositivo y Uso</div>", unsafe_allow_html=True)

q14 = st.radio(
    "**14.** ¿Desde dónde usas la app principalmente?",
    options=[
        "A) Solo computadora",
        "B) Solo celular",
        "C) Ambos — principalmente computadora",
        "D) Ambos — principalmente celular",
    ],
    index=["A)", "B)", "C)", "D)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)"] if answers.get("q14","").startswith(o)), "A)")
    ) if answers.get("q14") else 0,
    key="q14_radio",
)
answers["q14"] = q14

st.divider()

q15 = st.radio(
    "**15.** ¿A qué hora del día la usas más?",
    options=[
        "A) Antes de que abra el mercado (antes de 9:30 AM ET) — para planear",
        "B) Durante el mercado (9:30 AM – 4:00 PM ET) — trading activo",
        "C) Después del cierre — para revisar y preparar el día siguiente",
        "D) Varias veces al día",
    ],
    index=["A)", "B)", "C)", "D)"].index(
        next((o[:2] for o in ["A)", "B)", "C)", "D)"] if answers.get("q15","").startswith(o)), "A)")
    ) if answers.get("q15") else 0,
    key="q15_radio",
)
answers["q15"] = q15

# ── Extra comments ─────────────────────────────────────────────────────────────
st.markdown("<div class='section-label'>EXTRA — Comentarios libres</div>", unsafe_allow_html=True)
q_extra = st.text_area(
    "¿Hay algo más que quieras que sepa para el rediseño?",
    value=answers.get("q_extra", ""),
    placeholder="Cualquier cosa que no cubrieron las preguntas...",
    key="q_extra_input",
    height=100,
)
answers["q_extra"] = q_extra

# ── Save button ────────────────────────────────────────────────────────────────
st.divider()

answered_now = sum(1 for k in answers if answers[k] not in (None, [], "", False)
                   and not k.startswith("q12_"))
answered_now += sum(1 for k in ["q12_a","q12_b","q12_c","q12_d","q12_e","q12_f","q12_g"]
                    if answers.get(k))

col_btn, col_status = st.columns([1, 2])
with col_btn:
    if st.button("💾 Guardar respuestas", type="primary", use_container_width=True):
        save_answers(answers)
        st.session_state.saved = True

with col_status:
    if st.session_state.get("saved"):
        st.markdown(
            "<div class='saved-box'>"
            "<span style='color:#00d4aa;font-size:1.1rem;font-weight:700;'>✓ Guardado</span><br/>"
            "<span style='color:#888;font-size:0.85rem;'>Ahora dile a Claude que lea las respuestas</span>"
            "</div>",
            unsafe_allow_html=True,
        )

# Auto-save silently on change
save_answers(answers)
