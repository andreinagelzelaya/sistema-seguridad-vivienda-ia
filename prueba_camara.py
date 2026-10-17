"""
============================================================
PRUEBA DE CAMARA + MODELO + TELEGRAM (datos para el paper)
============================================================
Mide con datos REALES:
  1. Precision del modelo por clase (matriz de confusion).
  2. Confianza media, tiempo de inferencia y FPS.
  3. Efecto de la capa de verificacion (con y sin filtro).
  4. Tiempo hasta confirmar una deteccion.
  5. Latencia de Telegram (texto, foto, video).

Como se usa:
  - Pon la camara en su lugar de siempre (la entrada).
  - Cierra el sistema de seguridad (la camara solo la usa un programa).
  - python prueba_camara.py
  - Sigue las instrucciones de la ventana (ESPACIO = empezar ensayo,
    s = saltar ensayo, q = terminar y guardar).

Todo se guarda en la carpeta  resultados/
Usa config.py (mismo modelo y mismos parametros del sistema).
============================================================
"""

import os
import sys

os.environ["TF_USE_LEGACY_KERAS"] = "1"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

try:
    import config as cfg
except ImportError:
    print("ERROR: no existe config.py en esta carpeta.")
    sys.exit(1)

import csv
import time
import platform
from datetime import datetime

import cv2
import numpy as np
import requests
from tf_keras.models import load_model
from tf_keras.layers import DepthwiseConv2D

# ==================== Parametros de la prueba ====================
N_ENSAYOS = 6            # ensayos por clase
DURACION_S = 15          # segundos grabando por ensayo
CUENTA_ATRAS_S = 5       # tiempo para acomodarse antes de grabar
CONDICIONES = ["luz artificial (foco)"] * 6

UMBRAL = cfg.UMBRAL_CONFIANZA
FRAMES = cfg.FRAMES_CONFIRMA
ORDEN = ["vacio", "dueno", "externo"]
INSTRUCCION = {
    "vacio": "Deja la entrada VACIA (sal del cuadro durante la cuenta atras)",
    "dueno": f"{cfg.NOMBRE_DUENO} en la entrada: entra, quedate, gira, muevete natural",
    "externo": "OTRA persona en la entrada (si puedes, una distinta en cada ensayo)",
}
ES_WINDOWS = platform.system() == "Windows"
BACKEND_CAM = cv2.CAP_DSHOW if ES_WINDOWS else cv2.CAP_ANY
CARPETA = "resultados"
os.makedirs(CARPETA, exist_ok=True)
SELLO = datetime.now().strftime("%Y%m%d_%H%M")
VENTANA = "Prueba de camara (paper)"


# ==================== Modelo (igual que el sistema) ====================
class DepthwiseConv2DCompat(DepthwiseConv2D):
    def __init__(self, *args, **kwargs):
        kwargs.pop("groups", None)
        super().__init__(*args, **kwargs)


print("Cargando modelo...")
modelo = load_model(cfg.ARCHIVO_MODELO, compile=False,
                    custom_objects={"DepthwiseConv2D": DepthwiseConv2DCompat})
with open(cfg.ARCHIVO_LABELS, encoding="utf-8") as f:
    clases = [l.strip() for l in f if l.strip()]
clases = [c.split(" ", 1)[1] if " " in c else c for c in clases]
TIPO_POR_CLASE = {cfg.CLASE_VACIO.lower(): "vacio",
                  cfg.CLASE_DUENO.lower(): "dueno",
                  cfg.CLASE_EXTERNO.lower(): "externo"}
TIPOS_MODELO = [TIPO_POR_CLASE.get(c.lower(), "?") for c in clases]
if "?" in TIPOS_MODELO:
    print("ERROR: los nombres de labels.txt no coinciden con config.py:", clases)
    sys.exit(1)
print("Clases:", clases)


def predecir(frame):
    img = cv2.resize(frame, (224, 224))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
    arr = np.expand_dims((img / 127.5) - 1.0, axis=0)
    return np.array(modelo(arr, training=False))[0]


# ==================== Pantalla ====================
def texto(img, t, y, escala=0.8, color=(255, 255, 255), grosor=2):
    cv2.putText(img, t, (20, y), cv2.FONT_HERSHEY_SIMPLEX, escala, (0, 0, 0), grosor + 3, cv2.LINE_AA)
    cv2.putText(img, t, (20, y), cv2.FONT_HERSHEY_SIMPLEX, escala, color, grosor, cv2.LINE_AA)


def leer(cap):
    for _ in range(20):
        ok, frame = cap.read()
        if ok:
            return frame
        time.sleep(0.05)
    raise RuntimeError("La camara no manda imagen.")


# ==================== Ensayos ====================
def correr_ensayos(cap):
    filas = []
    plan = [(t, i) for t in ORDEN for i in range(N_ENSAYOS)]
    muestras = set()
    n = 0
    while n < len(plan):
        tipo, i = plan[n]
        cond = CONDICIONES[i % len(CONDICIONES)]
        ensayo_id = n + 1

        # --- espera ESPACIO ---
        while True:
            frame = leer(cap)
            v = frame.copy()
            texto(v, f"Ensayo {ensayo_id}/{len(plan)}  -  clase real: {tipo.upper()}", 40, 0.9, (0, 220, 255))
            texto(v, INSTRUCCION[tipo], 80, 0.6)
            texto(v, f"Condicion: {cond}", 110, 0.6)
            texto(v, "ESPACIO = empezar   s = saltar   q = terminar y guardar", 150, 0.6, (180, 180, 180), 1)
            cv2.imshow(VENTANA, v)
            k = cv2.waitKey(30) & 0xFF
            if k == ord(" "):
                break
            if k == ord("s"):
                print(f"Ensayo {ensayo_id} saltado.")
                break
            if k in (ord("q"), 27):
                return filas
        if k == ord("s"):
            n += 1
            continue

        # --- cuenta atras ---
        fin = time.time() + CUENTA_ATRAS_S
        while time.time() < fin:
            v = leer(cap).copy()
            texto(v, f"Empieza en {fin - time.time():.0f} s", 60, 1.4, (0, 220, 255), 3)
            texto(v, INSTRUCCION[tipo], 110, 0.6)
            cv2.imshow(VENTANA, v)
            cv2.waitKey(1)

        # --- grabacion ---
        t0 = time.perf_counter()
        while True:
            frame = leer(cap)
            t_rel = time.perf_counter() - t0
            if t_rel > DURACION_S:
                break
            ti = time.perf_counter()
            probs = predecir(frame)
            infer_ms = (time.perf_counter() - ti) * 1000
            idx = int(np.argmax(probs))
            filas.append({
                "ensayo": ensayo_id, "clase_real": tipo, "condicion": cond,
                "t_s": round(t_rel, 4), "pred": TIPOS_MODELO[idx],
                "confianza": round(float(probs[idx]), 5),
                **{f"p_{TIPOS_MODELO[j]}": round(float(probs[j]), 5) for j in range(len(clases))},
                "inferencia_ms": round(infer_ms, 2),
            })
            if tipo not in muestras and t_rel > DURACION_S / 2:
                cv2.imwrite(os.path.join(CARPETA, f"muestra_{tipo}_{SELLO}.jpg"), frame)
                muestras.add(tipo)
            v = frame.copy()
            texto(v, f"REC ensayo {ensayo_id}  {DURACION_S - t_rel:.0f} s", 40, 0.9, (0, 0, 255))
            texto(v, f"Modelo: {TIPOS_MODELO[idx].upper()} {probs[idx]:.0%}", 80, 0.8)
            cv2.imshow(VENTANA, v)
            if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                return filas
        print(f"Ensayo {ensayo_id} ({tipo}, {cond}) listo.")
        n += 1
    return filas


# ==================== Telegram ====================
def prueba_telegram(cap):
    api = f"https://api.telegram.org/bot{cfg.TOKEN}"
    chat = str(cfg.CHAT_ID)
    filas = []

    def medir(tipo, i, func):
        t = time.perf_counter()
        try:
            r = func()
            ok = r.status_code == 200 and r.json().get("ok", False)
        except Exception:
            ok = False
        filas.append({"tipo": tipo, "n": i, "segundos": round(time.perf_counter() - t, 3), "ok": ok})
        print(f"  {tipo} {i}: {filas[-1]['segundos']} s  ok={ok}")
        time.sleep(1.5)  # respetar limites de Telegram

    foto = os.path.join(CARPETA, "tmp_foto.jpg")
    cv2.imwrite(foto, leer(cap))
    for i in range(1, 11):
        medir("texto", i, lambda: requests.post(f"{api}/sendMessage", timeout=30,
              data={"chat_id": chat, "text": f"🧪 Prueba de latencia {i}/10"}))
    for i in range(1, 6):
        def enviar():
            with open(foto, "rb") as f:
                return requests.post(f"{api}/sendPhoto", data={"chat_id": chat,
                                     "caption": f"🧪 Prueba foto {i}/5"}, files={"photo": f}, timeout=60)
        medir("foto", i, enviar)
    for i in range(1, 4):
        video = os.path.join(CARPETA, "tmp_video.mp4")
        frame = leer(cap)
        h, w = frame.shape[:2]
        out = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
        fin = time.time() + 8          # igual que SEGUNDOS_VIDEO_EVIDENCIA
        while time.time() < fin:
            out.write(leer(cap))
            time.sleep(0.1)
        out.release()
        tam_kb = os.path.getsize(video) / 1024

        def enviar_v():
            with open(video, "rb") as f:
                return requests.post(f"{api}/sendVideo", data={"chat_id": chat,
                                     "caption": f"🧪 Prueba video {i}/3"}, files={"video": f}, timeout=120)
        medir("video", i, enviar_v)
        filas[-1]["tam_kb"] = round(tam_kb, 1)
    for tmp in ("tmp_foto.jpg", "tmp_video.mp4"):
        try:
            os.remove(os.path.join(CARPETA, tmp))
        except OSError:
            pass
    return filas


# ==================== Analisis ====================
def simular(seq, umbral, frames):
    """Misma logica del sistema: devuelve lista de (indice, tipo) confirmados."""
    contador, prev, ultima, alertas = 0, None, None, []
    for i, (t, c) in enumerate(seq):
        if c >= umbral:
            contador = contador + 1 if t == prev else 1
            prev = t
        else:
            contador, prev = 0, None
        if contador >= frames and t != ultima:
            alertas.append((i, t))
            ultima = t
    return alertas


def analizar(filas, tg):
    L = []
    p = L.append
    p(f"RESUMEN PRUEBA DE CAMARA - {SELLO}")
    p(f"Parametros: umbral={UMBRAL}, frames={FRAMES}, ensayos/clase={N_ENSAYOS}, duracion={DURACION_S}s")
    if not filas:
        p("Sin datos.")
        return "\n".join(L)

    # Matriz de confusion
    m = {r: {c: 0 for c in ORDEN} for r in ORDEN}
    for f in filas:
        m[f["clase_real"]][f["pred"]] += 1
    total = sum(sum(v.values()) for v in m.values())
    correctos = sum(m[c][c] for c in ORDEN)
    p(f"\nFrames analizados: {total}")
    p(f"Exactitud global: {correctos / total:.2%} ({correctos}/{total})")
    p("\nMatriz de confusion (filas = real, columnas = predicho):")
    p("            " + "".join(f"{c:>10}" for c in ORDEN))
    for r in ORDEN:
        p(f"{r:>10}  " + "".join(f"{m[r][c]:>10}" for c in ORDEN))

    p("\nPor clase: precision | sensibilidad | F1 | confianza media (aciertos)")
    f1s = []
    for c in ORDEN:
        tp = m[c][c]
        fp = sum(m[r][c] for r in ORDEN if r != c)
        fn = sum(m[c][x] for x in ORDEN if x != c)
        pr = tp / (tp + fp) if tp + fp else 0
        rc = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0
        f1s.append(f1)
        confs = [f["confianza"] for f in filas if f["clase_real"] == c and f["pred"] == c]
        p(f"{c:>10}: {pr:.2%} | {rc:.2%} | {f1:.3f} | {np.mean(confs) if confs else 0:.2%}")
    p(f"F1 macro: {np.mean(f1s):.3f}")

    # Rendimiento
    inf = np.array([f["inferencia_ms"] for f in filas])
    p(f"\nInferencia: media {inf.mean():.1f} ms, DE {inf.std():.1f} ms, "
      f"min {inf.min():.1f}, max {inf.max():.1f}, p95 {np.percentile(inf, 95):.1f} ms")
    fps = []
    for e in sorted({f["ensayo"] for f in filas}):
        ts = [f["t_s"] for f in filas if f["ensayo"] == e]
        if len(ts) > 1:
            fps.append((len(ts) - 1) / (ts[-1] - ts[0]))
    if fps:
        p(f"FPS de procesamiento: media {np.mean(fps):.1f} (min {min(fps):.1f}, max {max(fps):.1f})")

    # Capa de verificacion
    p("\nCapa de verificacion por ensayo (avisos = dueno/externo confirmados):")
    p("ensayo | real | t_confirmacion | avisos_correctos | avisos_incorrectos | "
      "cambios_sin_filtro | avisos_incorrectos_sin_filtro")
    tot = {"ok": 0, "mal": 0, "sf_cambios": 0, "sf_mal": 0}
    tconf = []
    for e in sorted({f["ensayo"] for f in filas}):
        fe = [f for f in filas if f["ensayo"] == e]
        real = fe[0]["clase_real"]
        seq = [(f["pred"], f["confianza"]) for f in fe]
        con = simular(seq, UMBRAL, FRAMES)
        sin = simular(seq, 0.0, 1)
        primero = next((i for i, t in con if t == real), None)
        t_c = fe[primero]["t_s"] if primero is not None else None
        if t_c is not None:
            tconf.append(t_c)
        ok = sum(1 for _, t in con if t == real and t != "vacio")
        mal = sum(1 for _, t in con if t != real and t != "vacio")
        sf_mal = sum(1 for _, t in sin if t != real and t != "vacio")
        cambios = max(len(sin) - 1, 0)
        tot["ok"] += ok; tot["mal"] += mal; tot["sf_cambios"] += cambios; tot["sf_mal"] += sf_mal
        p(f"{e:>6} | {real:>7} | {('%.2f s' % t_c) if t_c is not None else 'no confirmo':>12} | "
          f"{ok:>3} | {mal:>3} | {cambios:>4} | {sf_mal:>4}")
    p(f"TOTAL avisos incorrectos: con filtro {tot['mal']}  vs  sin filtro {tot['sf_mal']}")
    p(f"TOTAL cambios de clase sin filtro: {tot['sf_cambios']}")
    if tconf:
        p(f"Tiempo hasta confirmar: media {np.mean(tconf):.2f} s, min {min(tconf):.2f}, max {max(tconf):.2f}")

    # Telegram
    if tg:
        p("\nLatencia Telegram (s): tipo | n | media | min | max | exitos")
        for tipo in ("texto", "foto", "video"):
            v = [r["segundos"] for r in tg if r["tipo"] == tipo]
            okn = sum(1 for r in tg if r["tipo"] == tipo and r["ok"])
            if v:
                p(f"{tipo:>6} | {len(v)} | {np.mean(v):.2f} | {min(v):.2f} | {max(v):.2f} | {okn}/{len(v)}")
        kb = [r.get("tam_kb") for r in tg if r.get("tam_kb")]
        if kb:
            p(f"Tamano video 8 s: media {np.mean(kb):.0f} KB")
    return "\n".join(L)


def guardar_csv(nombre, filas):
    if not filas:
        return None
    ruta = os.path.join(CARPETA, nombre)
    campos = list(dict.fromkeys(k for f in filas for k in f))
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    return ruta


# ==================== Main ====================
def main():
    cap = cv2.VideoCapture(cfg.CAMARA, BACKEND_CAM)
    if not cap.isOpened():
        print("ERROR: no se pudo abrir la camara (¿el sistema sigue corriendo?).")
        return
    for _ in range(10):
        cap.read()
    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)

    filas = correr_ensayos(cap)
    cv2.destroyAllWindows()
    guardar_csv(f"camara_frames_{SELLO}.csv", filas)

    tg = []
    if input("\n¿Medir latencia de Telegram? Manda 18 mensajes de prueba (s/n): ").strip().lower() == "s":
        tg = prueba_telegram(cap)
        guardar_csv(f"telegram_{SELLO}.csv", tg)
    cap.release()

    resumen = analizar(filas, tg)
    with open(os.path.join(CARPETA, f"camara_resumen_{SELLO}.txt"), "w", encoding="utf-8") as f:
        f.write(resumen)
    print("\n" + resumen)
    print(f"\nListo. Archivos en la carpeta '{CARPETA}'.")


if __name__ == "__main__":
    main()
