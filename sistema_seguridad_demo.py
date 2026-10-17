"""
============================================================
SISTEMA DE SEGURIDAD CON IA - VERSION PARA GRABAR EL VIDEO
============================================================
Es el mismo sistema (camara + IA + filtro + red WiFi + Telegram),
pero con un TABLERO en pantalla para que se vea que funciona:

  - Camara en vivo con el % de cada clase (Teachable Machine).
  - Barra "Verificando 0/10": el filtro anti falsas alarmas.
  - Contador de detecciones sueltas DESCARTADAS por el filtro.
  - Reloj con segundos: se compara con la hora de Telegram
    y demuestra que el video es en vivo, sin cortes.
  - Panel de la red WiFi con los equipos conectados en vivo.
  - Registro de eventos y cuanto tardo cada envio a Telegram.

Configuracion: usa config.py si existe. Si no, lee los datos
(TOKEN, CHAT_ID, CONOCIDOS...) de tu sistema_seguridad.py SIN
ejecutarlo. Necesita keras_model.h5 y labels.txt en la carpeta.

IMPORTANTE: cierra sistema_seguridad.py antes de abrir este
(dos programas no pueden leer el mismo bot al mismo tiempo).

Teclas:  q salir | a armar/desarmar | r reiniciar | f pantalla completa
============================================================
"""

import os
import sys
import ast

os.environ["TF_USE_LEGACY_KERAS"] = "1"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

# ==================== AJUSTES DE LA DEMO ====================
COOLDOWN_DEMO_S = 20     # el sistema real usa 90 s; aqui menos para que el video no sea largo
SEGUNDOS_VIDEO = 8       # video de evidencia cuando tocas "Desconocido"
OCULTAR_MAC = True       # muestra solo el final de las MAC (pantalla y Telegram)
VENTANA = "Sistema de Seguridad con IA - Andrei Nagel Zelaya"


# ==================== Configuracion ====================
def leer_constantes(archivo):
    """Lee las constantes de un .py sin ejecutarlo."""
    datos = {}
    try:
        with open(archivo, encoding="utf-8") as f:
            arbol = ast.parse(f.read())
    except Exception:
        return datos
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
            try:
                datos[nodo.targets[0].id] = ast.literal_eval(nodo.value)
            except Exception:
                pass
    return datos


if os.path.exists("config.py"):
    CFG = leer_constantes("config.py")
    ORIGEN_CFG = "config.py"
else:
    CFG = leer_constantes("sistema_seguridad.py")
    ORIGEN_CFG = "sistema_seguridad.py"

TOKEN = str(CFG.get("TOKEN", ""))
CHAT_ID = str(CFG.get("CHAT_ID", ""))
if not TOKEN or "PON_AQUI" in TOKEN or not CHAT_ID or "PON_AQUI" in CHAT_ID:
    print(f"ERROR: no encontre TOKEN y CHAT_ID validos en {ORIGEN_CFG}.")
    print("Pon este archivo en la misma carpeta que tu sistema_seguridad.py o tu config.py.")
    sys.exit(1)

ARCHIVO_MODELO = CFG.get("ARCHIVO_MODELO", "keras_model.h5")
ARCHIVO_LABELS = CFG.get("ARCHIVO_LABELS", "labels.txt")
CAMARA = CFG.get("CAMARA", 0)
UMBRAL = float(CFG.get("UMBRAL_CONFIANZA", 0.90))
FRAMES = int(CFG.get("FRAMES_CONFIRMA", 10))
INTERVALO_S = CFG.get("INTERVALO_S", 3)
UMBRAL_AUSENCIA = CFG.get("UMBRAL_AUSENCIA", 3)
REDES = CFG.get("REDES_CASA") or [CFG.get("RED_CASA", "192.168.0")]
VIGILAR_RED = CFG.get("VIGILAR_RED", True)
CONOCIDOS = {k.lower(): v for k, v in CFG.get("CONOCIDOS", {}).items()}

for archivo in (ARCHIVO_MODELO, ARCHIVO_LABELS):
    if not os.path.exists(archivo):
        print(f"ERROR: falta '{archivo}' en esta carpeta.")
        sys.exit(1)

import time
import json
import socket
import platform
import threading
import subprocess
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import requests
from tf_keras.models import load_model
from tf_keras.layers import DepthwiseConv2D

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: falta Pillow. Instala con:  venv\\Scripts\\pip install pillow")
    sys.exit(1)

ES_WINDOWS = platform.system() == "Windows"
SIN_VENTANA = 0x08000000 if ES_WINDOWS else 0
BACKEND_CAM = cv2.CAP_DSHOW if ES_WINDOWS else cv2.CAP_ANY
API = f"https://api.telegram.org/bot{TOKEN}"
CARPETA = "evidencia_demo"
os.makedirs(CARPETA, exist_ok=True)


# ==================== Modelo ====================
class DepthwiseConv2DCompat(DepthwiseConv2D):
    def __init__(self, *args, **kwargs):
        kwargs.pop("groups", None)
        super().__init__(*args, **kwargs)


print("Cargando modelo de Teachable Machine...")
modelo = load_model(ARCHIVO_MODELO, compile=False, custom_objects={"DepthwiseConv2D": DepthwiseConv2DCompat})
with open(ARCHIVO_LABELS, encoding="utf-8") as f:
    clases = [l.strip() for l in f if l.strip()]
clases = [c.split(" ", 1)[1] if " " in c else c for c in clases]


def tipo_de(clase):
    c = clase.lower()
    if c == str(CFG.get("CLASE_VACIO", "vacio")).lower() or "vac" in c:
        return "vacio"
    if c == str(CFG.get("CLASE_EXTERNO", "externo")).lower() or "extern" in c:
        return "externo"
    return "dueno"


TIPOS = [tipo_de(c) for c in clases]
NOMBRE = CFG.get("NOMBRE_DUENO") or next((c for c, t in zip(clases, TIPOS) if t == "dueno"), "Dueno")
print("Clases:", dict(zip(clases, TIPOS)))

# Colores (BGR) - misma plantilla que la presentacion ("Bitacora nocturna")
def _bgr(h):
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


PAPEL = _bgr("F3EFE6")
TARJETA = _bgr("FBF9F4")
MARCO = _bgr("FDFCF8")
ARENA = _bgr("DCD3C1")
TINTA = _bgr("26242C")
MUTE = _bgr("6B675F")
NOCHE = _bgr("25346E")
AMBAR = _bgr("E8833A")
AMBAR_C = _bgr("F7CDA0")
ROJO = _bgr("C8443A")
VERDE = _bgr("3E8E6B")
INDIGO = _bgr("425CAA")
# nombres usados por los eventos
BLANCO, GRIS, VERDE_L, ROJO_L, AMBAR_L = TINTA, MUTE, VERDE, ROJO, AMBAR
COLOR_TIPO = {"vacio": MUTE, "dueno": NOCHE, "externo": ROJO}
TEXTO_TIPO = {"vacio": "Vacío", "dueno": NOMBRE, "externo": "Externo"}



def predecir(frame):
    img = cv2.resize(frame, (224, 224))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
    return np.array(modelo(np.expand_dims(img / 127.5 - 1.0, 0), training=False))[0]


# ==================== Estado compartido ====================
lock = threading.Lock()
lock_frame = threading.Lock()
ultimo_frame = None
armado = True
eventos = []                 # (hora, texto, color)
equipos = {}                 # mac -> {ip, fab, misses}
estado_red = "iniciando..."
duracion_barrido = 0.0
avisos_enviados = 0
descartadas = 0
ultima_latencia = None
bot_nombre = ""
flash_hasta, flash_color = 0.0, BLANCO
offset_tg = 0
silencio_hasta = 0.0
historial = []               # {t, tipo, detalle} (igual que el sistema real)
diario = {}                  # mac -> {llegada, salida}
ARCHIVO_HISTORIAL = "historial.csv"
ARCHIVO_CONOCIDOS = "conocidos.json"
ARCHIVO_DIARIO = "diario.json"
HORA_RESUMEN = CFG.get("HORA_RESUMEN", 21)


def evento(texto, color=BLANCO):
    hora = datetime.now().strftime("%H:%M:%S")
    with lock:
        eventos.append((hora, texto, color))
        del eventos[:-40]
    print(hora, texto)


def flash(color, seg=1.5):
    global flash_hasta, flash_color
    flash_color, flash_hasta = color, time.time() + seg


def mac_vis(mac):
    return ("··:··:··:··:" + mac[-5:]) if OCULTAR_MAC else mac


# ==================== Utilidades (iguales al sistema real) ====================
def log(tipo, detalle):
    ahora = datetime.now()
    with lock:
        historial.append({"t": ahora, "tipo": tipo, "detalle": detalle})
    try:
        with open(ARCHIVO_HISTORIAL, "a", encoding="utf-8") as f:
            f.write(f"{ahora.strftime('%Y-%m-%d %H:%M:%S')},{tipo},{detalle}\n")
    except Exception:
        pass


def resumen_texto():
    with lock:
        hoy = [h for h in historial if h["t"].date() == date.today()]
    conex = sum(1 for h in hoy if h["tipo"] == "conexion")
    desc = sum(1 for h in hoy if h["tipo"] == "desconexion")
    cam = sum(1 for h in hoy if h["tipo"] == "camara")
    return (f"📊 Resumen del día\nConexiones: {conex}\nDesconexiones: {desc}\n"
            f"Eventos de cámara: {cam}\nEventos totales: {len(hoy)}")


def leer_eventos_desde(dias):
    limite = datetime.now() - timedelta(days=dias)
    ev = []
    try:
        with open(ARCHIVO_HISTORIAL, encoding="utf-8") as f:
            for linea in f:
                p = linea.strip().split(",", 2)
                if len(p) >= 2:
                    try:
                        t = datetime.strptime(p[0], "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                    if t >= limite:
                        ev.append((t, p[1]))
    except Exception:
        pass
    return ev


def resumen_semanal_texto():
    ev = leer_eventos_desde(7)
    conex = sum(1 for _, t in ev if t == "conexion")
    desc = sum(1 for _, t in ev if t == "desconexion")
    cam = sum(1 for _, t in ev if t == "camara")
    return (f"📅 Resumen semanal (7 días)\nConexiones: {conex}\nDesconexiones: {desc}\n"
            f"Eventos de cámara: {cam}\nEventos totales: {len(ev)}")


def cargar_json(archivo, destino):
    try:
        with open(archivo, encoding="utf-8") as f:
            destino.update(json.load(f))
    except Exception:
        pass


def guardar_json(archivo, datos):
    try:
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
    except Exception:
        pass


def duracion(delta):
    seg = int(delta.total_seconds())
    h, m = seg // 3600, (seg % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"


def parse_tiempo(s):
    s = s.lower().strip()
    try:
        if s.endswith("h"):
            return int(float(s[:-1]) * 60)
        if s.endswith("m"):
            return int(s[:-1])
        return int(s)
    except ValueError:
        return 0


def en_silencio():
    return time.time() < silencio_hasta


def avisos_activos():
    return armado and not en_silencio()


# ==================== Telegram ====================
def _post(metodo, **kw):
    """Envia a Telegram y mide cuanto tarda (se muestra en pantalla)."""
    global ultima_latencia, avisos_enviados
    t0 = time.time()
    try:
        r = requests.post(f"{API}/{metodo}", timeout=60, **kw)
        dt = time.time() - t0
        if r.status_code == 200:
            ultima_latencia = dt
            avisos_enviados += 1
            evento(f"Telegram: entregado en {dt:.2f} s", AMBAR_L)
        else:
            evento(f"Telegram error {r.status_code}", ROJO_L)
    except Exception as e:
        evento("Telegram sin conexión", ROJO_L)
        print("Error Telegram:", e)


def en_hilo(func, *args, **kw):
    threading.Thread(target=func, args=args, kwargs=kw, daemon=True).start()


def telegram(texto):
    _post("sendMessage", data={"chat_id": CHAT_ID, "text": texto})


TECLADO = {"keyboard": [["📸 Foto", "🎥 Video"],
                        ["📊 Estado", "📖 Diario", "📅 Resumen"],
                        ["🔔 Armar", "🔇 Desarmar", "🔕 Silencio 1h"],
                        ["🗒️ Historial", "❓ Ayuda"]], "resize_keyboard": True}
BOTONES = {"📸 Foto": "/foto", "🎥 Video": "/video", "📊 Estado": "/estado",
           "📖 Diario": "/diario", "📅 Resumen": "/resumen", "🔔 Armar": "/armar",
           "🔇 Desarmar": "/desarmar", "🔕 Silencio 1h": "/silencio 1h",
           "🗒️ Historial": "/historial", "❓ Ayuda": "/ayuda"}
AYUDA = ("🛡️ Comandos del sistema\n\n"
         "📸 /foto – foto en vivo de la entrada\n"
         "🎥 /video – video en vivo de 5 s\n"
         "📊 /estado – equipos conectados al WiFi\n"
         "📖 /diario – llegadas y salidas de hoy\n"
         "🗒️ /historial – últimos 10 eventos\n"
         "📅 /resumen – resumen del día\n"
         "📆 /semana – resumen de 7 días\n"
         "📎 /exportar – historial completo (CSV)\n"
         "🔔 /armar  ·  🔇 /desarmar – activar o apagar avisos\n"
         "🔕 /silencio 2h – silenciar por un tiempo (30m, 2h)\n"
         "👥 /conocidos – equipos con nombre\n"
         "➕ /agregar MAC nombre  ·  ➖ /quitar MAC")


def telegram_menu(texto):
    _post("sendMessage", json={"chat_id": CHAT_ID, "text": texto, "reply_markup": TECLADO})


def enviar_foto(ruta, caption="", botones=False):
    data = {"chat_id": CHAT_ID, "caption": caption}
    if botones:
        data["reply_markup"] = json.dumps({"inline_keyboard": [[
            {"text": "✅ Es conocido", "callback_data": "ok"},
            {"text": "🚨 Desconocido", "callback_data": "no"}]]})
    with open(ruta, "rb") as f:
        _post("sendPhoto", data=data, files={"photo": f})


def enviar_documento(ruta):
    if not os.path.exists(ruta):
        telegram("Aún no hay historial para exportar.")
        return
    with open(ruta, "rb") as f:
        _post("sendDocument", data={"chat_id": CHAT_ID, "caption": "📎 Historial completo"}, files={"document": f})


def enviar_video(ruta, caption=""):
    with open(ruta, "rb") as f:
        _post("sendVideo", data={"chat_id": CHAT_ID, "caption": caption}, files={"video": f})


def frame_actual():
    with lock_frame:
        return None if ultimo_frame is None else ultimo_frame.copy()


def guardar_foto(frame, nota=""):
    f = frame.copy()
    cv2.putText(f, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    if nota:
        cv2.putText(f, nota, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    ruta = os.path.join(CARPETA, datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg")
    cv2.imwrite(ruta, f)
    return ruta


def grabar_video(seg):
    frame = frame_actual()
    if frame is None:
        return None
    h, w = frame.shape[:2]
    ruta = os.path.join(CARPETA, datetime.now().strftime("%Y%m%d_%H%M%S") + ".mp4")
    out = cv2.VideoWriter(ruta, cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    fin = time.time() + seg
    while time.time() < fin:
        f = frame_actual()
        if f is not None:
            out.write(f)
        time.sleep(0.1)
    out.release()
    return ruta


def manejar_comando(texto):
    global armado, silencio_hasta
    partes = texto.strip().split()
    if not partes:
        return
    cmd, args = partes[0].lower().split("@")[0], partes[1:]
    evento(f"Comando recibido: {' '.join(partes)}", AMBAR_L)

    if cmd in ("/ayuda", "/start", "/help", "/menu"):
        telegram_menu(AYUDA)
    elif cmd == "/foto":
        f = frame_actual()
        if f is not None:
            enviar_foto(guardar_foto(f, "Foto por comando"), "📸 Foto en vivo de la entrada")
        else:
            telegram("No hay imagen de la cámara.")
    elif cmd == "/video":
        telegram("🎥 Grabando 5 segundos...")
        r = grabar_video(5)
        enviar_video(r, "🎥 Video en vivo") if r else telegram("No hay imagen de la cámara.")
    elif cmd == "/estado":
        with lock:
            lista = sorted(equipos.items(), key=lambda kv: [int(v) for v in kv[1]["ip"].split(".")])
        estado = "ARMADO" if armado else "DESARMADO"
        if en_silencio():
            estado += f" (silencio {int((silencio_hasta - time.time()) / 60) + 1} min)"
        if not lista:
            telegram(f"📊 Sistema {estado}\nNo hay datos de red (¿estás en casa?).")
        else:
            lineas = [f"📊 Sistema {estado}", f"📡 Conectados ahora: {len(lista)}"]
            for mac, d in lista:
                lineas.append(f"• {CONOCIDOS.get(mac, d['fab'])} · .{d['ip'].split('.')[-1]} ({mac_vis(mac)})")
            telegram("\n".join(lineas))
    elif cmd == "/diario":
        if not diario:
            telegram("Aún no hay registro de entradas/salidas.")
        else:
            lineas = ["📖 Diario:"]
            for mac, d in diario.items():
                lleg = d.get("llegada", "")[11:16] or "-"
                sal = d.get("salida", "")[11:16] or "-"
                lineas.append(f"• {CONOCIDOS.get(mac, mac_vis(mac))}: llegada {lleg} | salida {sal}")
            telegram("\n".join(lineas))
    elif cmd == "/historial":
        with lock:
            ult = historial[-10:]
        if not ult:
            telegram("Sin eventos aún.")
        else:
            telegram("🗒️ Últimos eventos:\n" + "\n".join(
                f"• {h['t'].strftime('%H:%M')} {h['tipo']}: {h['detalle']}" for h in ult))
    elif cmd == "/resumen":
        telegram(resumen_texto())
    elif cmd == "/semana":
        telegram(resumen_semanal_texto())
    elif cmd == "/exportar":
        enviar_documento(ARCHIVO_HISTORIAL)
    elif cmd == "/armar":
        armado = True
        silencio_hasta = 0.0
        evento("Sistema ARMADO", VERDE_L)
        telegram("🔔 Sistema ARMADO (red + cámara).")
    elif cmd == "/desarmar":
        armado = False
        evento("Sistema DESARMADO", GRIS)
        telegram("🔕 Sistema DESARMADO.")
    elif cmd == "/silencio":
        m = parse_tiempo(args[0]) if args else 0
        if m > 0:
            silencio_hasta = time.time() + m * 60
            evento(f"Silencio por {m} min", GRIS)
            telegram(f"🔕 Silenciado por {m} min. Usa /armar para reactivar antes.")
        else:
            telegram("Uso: /silencio 2h  o  /silencio 30m")
    elif cmd == "/agregar":
        if len(args) >= 2:
            mac, nombre = args[0].lower().replace("-", ":"), " ".join(args[1:])
            CONOCIDOS[mac] = nombre
            guardar_json(ARCHIVO_CONOCIDOS, CONOCIDOS)
            evento(f"Conocido agregado: {nombre}", VERDE_L)
            telegram(f"✅ Agregado: {nombre} ({mac_vis(mac)})")
        else:
            telegram("Uso: /agregar MAC nombre\nEj: /agregar aa:bb:cc:dd:ee:ff Mamá")
    elif cmd == "/quitar":
        mac = args[0].lower().replace("-", ":") if args else ""
        if mac and CONOCIDOS.pop(mac, None) is not None:
            guardar_json(ARCHIVO_CONOCIDOS, CONOCIDOS)
            evento("Conocido quitado", GRIS)
            telegram(f"🗑️ Quitado: {mac_vis(mac)}")
        else:
            telegram("Esa MAC no estaba, o falta la MAC.")
    elif cmd == "/conocidos":
        if not CONOCIDOS:
            telegram("No hay conocidos registrados.")
        else:
            telegram("👥 Conocidos:\n" + "\n".join(f"• {n} ({mac_vis(m)})" for m, n in CONOCIDOS.items()))
    else:
        telegram("No conozco ese comando. Usa /ayuda")


def hilo_telegram():
    global offset_tg, bot_nombre
    try:
        bot_nombre = requests.get(f"{API}/getMe", timeout=10).json()["result"]["username"]
        # menu de comandos de Telegram (boton "Menu" y lista al escribir "/")
        requests.post(f"{API}/setMyCommands", timeout=10, json={"commands": [
            {"command": c, "description": t} for c, t in [
                ("foto", "Foto en vivo de la entrada"), ("video", "Video en vivo de 5 s"),
                ("estado", "Equipos conectados al WiFi"), ("diario", "Llegadas y salidas"),
                ("historial", "Últimos 10 eventos"), ("resumen", "Resumen del día"),
                ("semana", "Resumen de 7 días"), ("exportar", "Historial completo (CSV)"),
                ("armar", "Activar avisos"), ("desarmar", "Apagar avisos"),
                ("silencio", "Silenciar: /silencio 30m o 2h"), ("conocidos", "Equipos con nombre"),
                ("agregar", "Agregar: /agregar MAC nombre"), ("quitar", "Quitar: /quitar MAC"),
                ("ayuda", "Ver todos los comandos")]]})
        r = requests.get(f"{API}/getUpdates", timeout=10).json()
        if r.get("result"):
            offset_tg = r["result"][-1]["update_id"] + 1
    except Exception:
        pass
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"offset": offset_tg, "timeout": 20}, timeout=30)
            if r.status_code == 409:
                evento("Cierra sistema_seguridad.py: está usando el bot", ROJO_L)
                time.sleep(5)
                continue
            r = r.json()
        except Exception:
            time.sleep(2)
            continue
        for upd in r.get("result", []):
            offset_tg = upd["update_id"] + 1
            origen = (upd.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
                      or upd.get("message", {}).get("chat", {}).get("id"))
            if str(origen) != CHAT_ID:
                continue   # solo obedece a tu chat
            if "callback_query" in upd:
                cq = upd["callback_query"]
                try:
                    requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cq["id"]}, timeout=10)
                except Exception:
                    pass
                if cq.get("data") == "ok":
                    evento("Respuesta: ES CONOCIDO", VERDE_L)
                    log("respuesta", "conocido")
                    telegram("✅ Marcado como conocido. Sin alarma.")
                else:
                    evento("Respuesta: DESCONOCIDO, grabando evidencia", ROJO_L)
                    log("respuesta", "DESCONOCIDO")
                    flash(ROJO_L, SEGUNDOS_VIDEO)
                    telegram("🚨 DESCONOCIDO confirmado. Grabando evidencia...")
                    r2 = grabar_video(SEGUNDOS_VIDEO)
                    if r2:
                        enviar_video(r2, "📹 Evidencia del desconocido")
                continue
            texto = upd.get("message", {}).get("text", "")
            if texto in BOTONES:
                manejar_comando(BOTONES[texto])
            elif texto.startswith("/"):
                manejar_comando(texto)


# ==================== Red WiFi (misma logica del sistema) ====================
def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def ping(ip):
    cmd = ["ping", "-n", "1", "-w", "1000", ip] if ES_WINDOWS else ["ping", "-c", "1", "-W", "1", ip]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=SIN_VENTANA)


def leer_arp(subred):
    disp = {}
    if ES_WINDOWS:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, creationflags=SIN_VENTANA).stdout
        for linea in out.splitlines():
            p = linea.split()
            if len(p) >= 2 and p[1].count("-") == 5 and p[0].startswith(subred + "."):
                mac = p[1].replace("-", ":").lower()
                try:
                    if int(mac.split(":")[0], 16) & 0x01:
                        continue
                except ValueError:
                    continue
                disp[mac] = p[0]
    else:
        out = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True).stdout
        for linea in out.splitlines():
            p = linea.split()
            if "lladdr" in p and p[-1] in ("REACHABLE", "DELAY", "PROBE") and p[0].startswith(subred + "."):
                disp[p[p.index("lladdr") + 1].lower()] = p[0]
    return disp


def fabricante(mac):
    try:
        if int(mac.split(":")[0], 16) & 0x02:
            return "MAC aleatoria"
        r = requests.get(f"https://api.macvendors.com/{mac}", timeout=5)
        time.sleep(1.1)   # limite de la API gratuita
        return r.text.strip()[:28] if r.status_code == 200 and r.text.strip() else "desconocido"
    except Exception:
        return "desconocido"


def hilo_red():
    global estado_red, duracion_barrido
    if not VIGILAR_RED:
        estado_red = "desactivado"
        return
    try:
        subred = ".".join(ip_local().split(".")[:3])
    except Exception:
        estado_red = "sin red"
        return
    if subred not in REDES:
        estado_red = f"{subred}.x no es tu casa: apagado"
        evento(f"Red {subred}.x no es la de casa: monitor apagado", GRIS)
        return
    estado_red = f"{subred}.x · activo"
    primera = True
    while True:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=64) as ex:
            list(ex.map(ping, [f"{subred}.{i}" for i in range(1, 255)]))
        disp = leer_arp(subred)
        duracion_barrido = time.time() - t0
        hora = datetime.now().strftime("%H:%M:%S")

        if primera:
            with lock:
                for mac, ip in disp.items():
                    equipos[mac] = {"ip": ip, "fab": CONOCIDOS.get(mac) or "consultando...", "misses": 0}
            evento(f"Red: {len(disp)} equipos encontrados", AMBAR_L)
            for mac in list(disp):
                if not CONOCIDOS.get(mac):
                    fab = fabricante(mac)
                    with lock:
                        if mac in equipos:
                            equipos[mac]["fab"] = fab
            primera = False
            time.sleep(INTERVALO_S)
            continue

        for mac, ip in disp.items():
            if mac not in equipos:
                nombre = CONOCIDOS.get(mac)
                fab = nombre or fabricante(mac)
                with lock:
                    equipos[mac] = {"ip": ip, "fab": fab, "misses": 0}
                if nombre:
                    evento(f"WiFi: llegó {nombre}", VERDE_L)
                    txt = f"👋 ¡Bienvenido {nombre}! Llegaste a casa."
                    d = diario.get(mac, {})
                    if d.get("salida"):
                        try:
                            txt += f"\nEstuviste fuera: {duracion(datetime.now() - datetime.fromisoformat(d['salida']))}"
                        except ValueError:
                            pass
                    d["llegada"] = datetime.now().isoformat()
                    diario[mac] = d
                    guardar_json(ARCHIVO_DIARIO, diario)
                    txt += f"\nHora: {hora}"
                    log("conexion", nombre)
                else:
                    evento(f"WiFi: equipo nuevo ({fab})", AMBAR_L)
                    txt = f"🟢 Dispositivo CONECTADO\nFabricante: {fab}\nMAC: {mac_vis(mac)}\nIP: {ip}\nHora: {hora}"
                    log("conexion", f"{fab} {mac_vis(mac)}")
                if avisos_activos():
                    en_hilo(telegram, txt)
            else:
                with lock:
                    equipos[mac]["misses"] = 0
                    equipos[mac]["ip"] = ip

        for mac in list(equipos.keys()):
            if mac not in disp:
                with lock:
                    equipos[mac]["misses"] += 1
                    fuera = equipos[mac]["misses"] >= UMBRAL_AUSENCIA
                    info = equipos.pop(mac) if fuera else None
                if fuera:
                    nombre = CONOCIDOS.get(mac)
                    if nombre:
                        evento(f"WiFi: se fue {nombre}", GRIS)
                        txt = f"👋 Hasta luego {nombre}, que te vaya bien."
                        d = diario.get(mac, {})
                        if d.get("llegada"):
                            try:
                                txt += f"\nEstuvo en casa: {duracion(datetime.now() - datetime.fromisoformat(d['llegada']))}"
                            except ValueError:
                                pass
                        d["salida"] = datetime.now().isoformat()
                        diario[mac] = d
                        guardar_json(ARCHIVO_DIARIO, diario)
                        txt += f"\nHora: {hora}"
                        log("desconexion", nombre)
                    else:
                        evento(f"WiFi: se desconectó ({info['fab']})", GRIS)
                        txt = f"🔴 Dispositivo DESCONECTADO\nFabricante: {info['fab']}\nMAC: {mac_vis(mac)}\nHora: {hora}"
                        log("desconexion", f"{info['fab']} {mac_vis(mac)}")
                    if avisos_activos():
                        en_hilo(telegram, txt)
        time.sleep(INTERVALO_S)


def hilo_resumen():
    ultimo_dia, ultimo_sem = None, None
    while True:
        ahora = datetime.now()
        if ahora.hour == HORA_RESUMEN:
            if ultimo_dia != date.today():
                telegram(resumen_texto())
                ultimo_dia = date.today()
            if ahora.weekday() == 6 and ultimo_sem != date.today():
                telegram(resumen_semanal_texto())
                ultimo_sem = date.today()
        time.sleep(30)


# ==================== Acciones de la camara ====================
def actuar(tipo, frame, conf):
    if tipo == "vacio":
        evento("Cámara: entrada vacía (sin aviso)", GRIS)
        return
    log("camara", TEXTO_TIPO[tipo])
    if not avisos_activos():
        evento(f"Cámara: {TEXTO_TIPO[tipo]} ({'silencio' if armado else 'desarmado'}, sin aviso)", GRIS)
        return
    if tipo == "dueno":
        evento(f"Cámara: {NOMBRE} confirmado ({conf:.0%})", VERDE_L)
        flash(VERDE_L)
        en_hilo(telegram, f"👋 ¡Bienvenido {NOMBRE}! (cámara, {conf:.0%})")
    else:
        evento(f"Cámara: EXTERNO confirmado ({conf:.0%})", ROJO_L)
        flash(ROJO_L)
        ruta = guardar_foto(frame, "Externo detectado")
        en_hilo(enviar_foto, ruta, f"⚠️ Persona detectada en la entrada ({conf:.0%}). ¿La reconoces?", botones=True)


# ==================== Dibujo (estilo de la presentacion) ====================
W, H = 1280, 720
FUENTES = {}
_DIR_WIN = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
_CAND = {   # Windows (Cambria / Calibri) y equivalentes libres
    "serif": ["cambria.ttc", "Caladea-Regular.ttf", "georgia.ttf", "DejaVuSerif.ttf"],
    "serifi": ["cambriai.ttf", "Caladea-Italic.ttf", "georgiai.ttf", "DejaVuSerif-Italic.ttf"],
    "sans": ["calibri.ttf", "Carlito-Regular.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "sansb": ["calibrib.ttf", "Carlito-Bold.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
}


def fuente(estilo, tam):
    clave = (estilo, tam)
    if clave not in FUENTES:
        FUENTES[clave] = None
        for n in _CAND[estilo]:
            for r in (os.path.join(_DIR_WIN, n), n, "/usr/share/fonts/truetype/crosextra/" + n,
                      "/usr/share/fonts/truetype/dejavu/" + n):
                try:
                    FUENTES[clave] = ImageFont.truetype(r, tam)
                    break
                except Exception:
                    pass
            if FUENTES[clave] is not None:
                break
    return FUENTES[clave]


def trazo(img, pts, color, grosor=2, semilla=0, amp=1.4):
    """Linea 'hecha a mano' (temblorosa), como los trazos de la presentacion."""
    P = np.array(pts, float)
    Q = []
    for a, b in zip(P[:-1], P[1:]):
        n = max(2, int(np.hypot(*(b - a)) / 5))
        Q += [a + (b - a) * t for t in np.linspace(0, 1, n, endpoint=False)]
    Q.append(P[-1])
    Q = np.array(Q)
    rng = np.random.default_rng(semilla)
    f, ph = rng.uniform(0.15, 0.3, 2), rng.uniform(0, 6.28, 2)
    s = np.arange(len(Q))
    Q[:, 0] += amp * np.sin(s * f[0] + ph[0])
    Q[:, 1] += amp * np.sin(s * f[1] + ph[1])
    cv2.polylines(img, [np.int32(Q * 4)], False, color, grosor, cv2.LINE_AA, shift=2)


def ovalo(img, cx, cy, rx, ry, color, grosor=3, semilla=0):
    t = np.linspace(-0.3, 2 * np.pi + 0.25, 70)
    r = 1 + 0.03 * np.sin(t * 3 + semilla)
    trazo(img, list(zip(cx + rx * r * np.cos(t), cy + ry * r * np.sin(t))), color, grosor, semilla, 1.0)


def rrect(img, x, y, w, h, color, r=10):
    x, y, w, h = int(x), int(y), int(w), int(h)
    cv2.rectangle(img, (x + r, y), (x + w - r, y + h), color, -1)
    cv2.rectangle(img, (x, y + r), (x + w, y + h - r), color, -1)
    for cx, cy in ((x + r, y + r), (x + w - r, y + r), (x + r, y + h - r), (x + w - r, y + h - r)):
        cv2.circle(img, (cx, cy), r, color, -1, cv2.LINE_AA if img.dtype == np.uint8 else cv2.LINE_8)


def sombra(img, x, y, w, h, r=10, fuerza=0.16):
    """Sombra suave solo en la zona de la tarjeta (rapido)."""
    g = 24
    x0, y0 = max(0, x - g), max(0, y - g)
    x1, y1 = min(img.shape[1], x + w + g), min(img.shape[0], y + h + g)
    m = np.zeros((y1 - y0, x1 - x0), np.float32)
    rrect(m, x + 2 - x0, y + 5 - y0, w, h, 1.0, r)
    m = cv2.GaussianBlur(m, (0, 0), 7)[..., None] * fuerza
    zona = img[y0:y1, x0:x1].astype(np.float32)
    img[y0:y1, x0:x1] = (zona * (1 - m) + np.array(_bgr("6B5E48"), np.float32) * m).astype(np.uint8)


# ---- zonas de la pantalla
CAM = (28, 112, 816, 459)                  # imagen de la camara (16:9) dentro del marco
MARCO_C = (CAM[0] - 12, CAM[1] - 12, CAM[2] + 24, CAM[3] + 24)
MOD = (16, 610, 840, 98)                   # tarjeta "lo que ve el modelo"
RX, RW = 876, 388                          # columna derecha
FIL = (RX, 100, RW, 168)
RED = (RX, 282, RW, 196)
EVT = (RX, 492, RW, 216)


def _fondo():
    rng = np.random.default_rng(11)
    img = np.ones((H, W, 3), np.float32) * np.array(PAPEL, np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.clip(1 - np.hypot(xx - 300, yy - 60) / 700, 0, 1) ** 2 * 0.5
    img = img * (1 - d[..., None]) + np.array(_bgr("F6DEC8"), np.float32) * d[..., None]
    img += rng.normal(0, 3.5, (H, W, 1))
    img = np.clip(img, 0, 255).astype(np.uint8)
    for (x, y, w, h) in (MARCO_C, MOD, FIL, RED, EVT):
        sombra(img, x, y, w, h)
    rrect(img, *MARCO_C, MARCO, 8)
    for (x, y, w, h) in (MOD, FIL, RED, EVT):
        rrect(img, x, y, w, h, TARJETA, 10)
    return img


FONDO = None
# cinta adhesiva sobre el marco de la camara
CINTA_W, CINTA_H = 150, 30
_c = np.ones((CINTA_H, CINTA_W, 3), np.uint8) * np.array(_bgr("E9DCBE"), np.uint8)
_c[:, ::9] = _bgr("E1D2B2")
CINTA = _c
CINTA_X, CINTA_Y = MARCO_C[0] + MARCO_C[2] // 2 - CINTA_W // 2, MARCO_C[1] - 14


class Lienzo:
    def __init__(self):
        global FONDO
        if FONDO is None:
            FONDO = _fondo()
        self.img = FONDO.copy()
        self.txt = []

    def text(self, x, y, t, tam=16, color=TINTA, estilo="sans", ancla="la"):
        self.txt.append(([(t, estilo, color)], x, y, tam, ancla))

    def runs(self, x, y, partes, tam, ancla="ls"):
        """Varias partes en una linea, ej. titulo con palabra en cursiva de color."""
        self.txt.append((partes, x, y, tam, ancla))

    def kicker(self, x, y, t):
        cv2.line(self.img, (x, y + 7), (x + 22, y + 7), AMBAR, 2, cv2.LINE_AA)
        self.text(x + 32, y, t, 12, MUTE, "sansb")

    def terminar(self):
        for partes, x, y, tam, ancla in self.txt:
            if len(partes) == 1:
                t, e, c = partes[0]
                pegar_texto(self.img, x, y, t, e, tam, c, ancla)
                continue
            total = sum(ancho(t, e, tam) for t, e, _ in partes)
            cx = x - total if ancla[0] == "r" else x
            for t, e, c in partes:
                pegar_texto(self.img, cx, y, t, e, tam, c, "l" + ancla[1])
                cx += ancho(t, e, tam)
        return self.img


_CACHE_TXT, _CACHE_AN = {}, {}


def ancho(t, e, tam):
    k = (t, e, tam)
    if k not in _CACHE_AN:
        _CACHE_AN[k] = fuente(e, tam).getlength(t)
    return _CACHE_AN[k]


def pegar_texto(img, x, y, t, e, tam, color, ancla):
    """Texto con PIL, guardado en cache (el texto que no cambia no se vuelve a dibujar)."""
    k = (t, e, tam, ancla)
    if k not in _CACHE_TXT:
        if len(_CACHE_TXT) > 3000:
            _CACHE_TXT.clear()
        f = fuente(e, tam)
        l, tp, r, b = f.getbbox(t, anchor=ancla)
        m = Image.new("L", (max(1, r - l + 4), max(1, b - tp + 4)), 0)
        ImageDraw.Draw(m).text((2 - l, 2 - tp), t, font=f, fill=255, anchor=ancla)
        _CACHE_TXT[k] = (np.asarray(m, np.float32)[..., None] / 255.0, l - 2, tp - 2)
    a, dx, dy = _CACHE_TXT[k]
    x0, y0 = int(round(x + dx)), int(round(y + dy))
    h, w = a.shape[:2]
    X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(img.shape[1], x0 + w), min(img.shape[0], y0 + h)
    if X1 <= X0 or Y1 <= Y0:
        return
    a = a[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    zona = img[Y0:Y1, X0:X1].astype(np.float32)
    img[Y0:Y1, X0:X1] = (zona * (1 - a) + np.array(color, np.float32) * a).astype(np.uint8)


def ajustar_marco(fw, fh):
    """El marco de la camara toma la forma de la imagen (4:3, 16:9...) y se centra: sin franjas."""
    global CAM, MARCO_C, CINTA_X, CINTA_Y, FONDO
    alto = 459
    ancho = min(816, int(round(alto * fw / fh)))
    alto = min(alto, int(round(ancho * fh / fw)))
    CAM = (28 + (816 - ancho) // 2, 112 + (459 - alto) // 2, ancho, alto)
    MARCO_C = (CAM[0] - 12, CAM[1] - 12, CAM[2] + 24, CAM[3] + 24)
    CINTA_X, CINTA_Y = MARCO_C[0] + MARCO_C[2] // 2 - CINTA_W // 2, MARCO_C[1] - 14
    FONDO = None


_forma = None


def dibujar(frame, probs, tipo, conf, contador, espera, fps):
    global _forma
    if _forma != frame.shape[:2]:
        _forma = frame.shape[:2]
        ajustar_marco(_forma[1], _forma[0])
    L = Lienzo()
    img = L.img
    ahora = datetime.now()
    alerta = time.time() < flash_hasta

    # ---- encabezado (igual que las diapositivas)
    L.kicker(32, 20, "SISTEMA EN VIVO  ·  ISW-221 INTELIGENCIA ARTIFICIAL")
    L.runs(32, 74, [("Seguridad de vivienda con ", "serif", TINTA), ("inteligencia artificial.", "serifi", AMBAR)], 34)
    L.text(RX + RW - 160, 52, ahora.strftime("%H:%M:%S"), 40, TINTA, "serif", "rs")
    L.text(RX + RW - 160, 72, ahora.strftime("%d/%m/%Y") + f"  ·  {fps:.0f} FPS", 12, MUTE, "sans", "ra")
    if armado and en_silencio():
        est, fondo, col_t = f"SILENCIO {int((silencio_hasta - time.time()) / 60) + 1}m", AMBAR, (255, 255, 255)
    elif armado:
        est, fondo, col_t = "ARMADO", NOCHE, (255, 255, 255)
    else:
        est, fondo, col_t = "DESARMADO", ARENA, MUTE
    rrect(img, RX + RW - 136, 26, 136, 34, fondo, 17)
    L.text(RX + RW - 68, 43, est, 14, col_t, "sansb", "mm")

    # ---- camara en su marco con cinta
    fh, fw = frame.shape[:2]
    x, y, w, h = CAM
    esc = min(w / fw, h / fh)
    vw, vh = int(fw * esc), int(fh * esc)
    vx, vy = x + (w - vw) // 2, y + (h - vh) // 2
    img[y:y + h, x:x + w] = _bgr("1B2654")
    img[vy:vy + vh, vx:vx + vw] = cv2.resize(frame, (vw, vh))
    if alerta:
        cv2.rectangle(img, (MARCO_C[0] + 3, MARCO_C[1] + 3), (MARCO_C[0] + MARCO_C[2] - 3, MARCO_C[1] + MARCO_C[3] - 3), flash_color, 6, cv2.LINE_AA)
    zona = img[CINTA_Y:CINTA_Y + CINTA_H, CINTA_X:CINTA_X + CINTA_W]
    zona[:] = cv2.addWeighted(zona, 0.25, CINTA, 0.75, 0)
    # "EN VIVO"
    rrect(img, x + w - 112, y + 14, 96, 28, TARJETA, 14)
    cv2.circle(img, (x + w - 94, y + 28), 6, ROJO if int(time.time() * 2) % 2 else ARENA, -1, cv2.LINE_AA)
    L.text(x + w - 82, y + 28, "EN VIVO", 13, ROJO, "sansb", "lm")

    # ---- tarjeta de prediccion sobre la camara (como la notificacion de la portada)
    px, py, pw, ph = x + 16, y + h - 86, 380, 70
    sombra(img, px, py, pw, ph, 12, 0.25)
    rrect(img, px, py, pw, ph, TARJETA, 12)
    seguro = conf >= UMBRAL
    col = COLOR_TIPO[tipo] if seguro else AMBAR
    cv2.circle(img, (px + 34, py + 35), 19, col, -1, cv2.LINE_AA)
    if seguro:
        trazo(img, [(px + 25, py + 36), (px + 32, py + 43), (px + 44, py + 27)], (255, 255, 255), 3, 1, 0.4)
    else:
        L.text(px + 34, py + 36, "?", 22, (255, 255, 255), "sansb", "mm")
    if seguro:
        L.runs(px + 66, py + 40, [(TEXTO_TIPO[tipo] + "  ", "serif", TINTA), (f"{conf:.0%}", "serifi", col)], 30)
        L.text(px + 66, py + 46, "seguro: cuenta para la verificación", 13, MUTE)
    else:
        L.runs(px + 66, py + 40, [("Dudoso  ", "serif", TINTA), (f"{conf:.0%}", "serifi", AMBAR)], 30)
        L.text(px + 66, py + 46, f"menos de {UMBRAL:.0%}: no cuenta", 13, MUTE)
    if alerta:  # trazos de atencion y ovalo a mano, como en la portada
        ovalo(img, px + pw / 2, py + ph / 2, pw / 2 + 18, ph / 2 + 14, flash_color, 3, 4)
        for i, (a, b, c, d) in enumerate(((px + pw + 14, py - 8, px + pw + 26, py - 26), (px + pw + 26, py + 4, px + pw + 44, py - 6))):
            trazo(img, [(a, b), (c, d)], flash_color, 3, i)

    # ---- lo que ve el modelo
    x, y, w, h = MOD
    L.kicker(x + 20, y + 12, "LO QUE VE EL MODELO")
    for i, c in enumerate(clases):
        cx = x + 20 + i * 272
        p = float(probs[i])
        colc = COLOR_TIPO[TIPOS[i]]
        L.runs(cx, y + 64, [(c, "serifi", colc)], 22)
        L.text(cx + 250, y + 64, f"{p:.1%}", 18, TINTA, "sansb", "rs")
        rrect(img, cx, y + 74, 250, 10, ARENA, 5)
        if p > 0.02:
            rrect(img, cx, y + 74, max(10, int(250 * p)), 10, colc, 5)
        ux = cx + int(250 * UMBRAL)
        cv2.line(img, (ux, y + 70), (ux, y + 88), AMBAR, 2, cv2.LINE_AA)

    # ---- filtro
    x, y, w, h = FIL
    L.kicker(x + 20, y + 14, "FILTRO ANTI FALSAS ALARMAS")
    n = min(contador, FRAMES)
    L.runs(x + 20, y + 78, [(f"{n}", "serif", NOCHE), (f" / {FRAMES}", "serif", MUTE)], 40)
    L.text(x + 160, y + 78, "imágenes seguras seguidas", 18, AMBAR, "serifi", "ls")
    trazo(img, [(x + 20, y + 88), (x + 60, y + 85), (x + 100, y + 89), (x + 135, y + 86)], AMBAR, 2, 7)
    for k in range(FRAMES):
        cv2.circle(img, (x + 32 + k * 25, y + 110), 9, NOCHE if k < n else ARENA, -1, cv2.LINE_AA)
    L.runs(x + 20, y + 150, [(f"{descartadas}", "serif", ROJO), ("  descartadas por el filtro", "serifi", MUTE)], 20)
    if espera > 0:
        L.text(x + w - 20, y + 150, f"espera {espera:.0f} s", 14, AMBAR, "sansb", "rs")

    # ---- red wifi
    x, y, w, h = RED
    L.kicker(x + 20, y + 14, "RED WIFI DE LA CASA")
    L.text(x + w - 20, y + 14, estado_red, 12, MUTE, "sans", "ra")
    with lock:
        lista = sorted(equipos.items(), key=lambda kv: [int(v) for v in kv[1]["ip"].split(".")])
    for i, (mac, d) in enumerate(lista[:5]):
        yy = y + 44 + i * 22
        nombre = CONOCIDOS.get(mac)
        cv2.circle(img, (x + 26, yy + 9), 5, VERDE, -1, cv2.LINE_AA)
        if nombre:
            L.runs(x + 40, yy + 15, [(nombre, "serifi", NOCHE), ("  conocido", "sans", MUTE)], 17)
        else:
            L.text(x + 40, yy + 1, d["fab"][:30], 14, TINTA)
        L.text(x + w - 20, yy + 1, f".{d['ip'].split('.')[-1]}   {mac[-5:]}", 13, MUTE, "sans", "ra")
    if len(lista) > 5:
        L.text(x + 40, y + 44 + 5 * 22, f"+{len(lista) - 5} más  (usa /estado)", 13, MUTE)
    L.text(x + 20, y + h - 22, f"{len(lista)} equipos · barrido {duracion_barrido:.1f} s · cada {INTERVALO_S} s", 12, MUTE)

    # ---- eventos
    x, y, w, h = EVT
    L.kicker(x + 20, y + 14, "EVENTOS")
    lat = f"Telegram: {ultima_latencia:.2f} s" if ultima_latencia else ("@" + bot_nombre if bot_nombre else "conectando bot...")
    L.text(x + w - 20, y + 14, lat, 12, MUTE, "sans", "ra")
    with lock:
        ult = eventos[-8:]
    for i, (hh, t, c) in enumerate(reversed(ult)):
        yy = y + 42 + i * 21
        L.text(x + 20, yy, hh, 13, MUTE)
        L.text(x + 82, yy, t[:42], 13, c)

    L.text(W - 16, H - 2, "q salir · a armar · r reiniciar · f pantalla completa", 10, MUTE, "sans", "rd")
    return L.terminar()



# ==================== Camara ====================
def abrir_camara():
    """Prueba varios backends e indices (DirectShow a veces falla y Media Foundation no, o al reves)."""
    backends = [(cv2.CAP_DSHOW, "DirectShow"), (cv2.CAP_MSMF, "Media Foundation"), (cv2.CAP_ANY, "automático")] \
        if ES_WINDOWS else [(cv2.CAP_ANY, "automático"), (cv2.CAP_V4L2, "V4L2")]
    indices = [CAMARA] + [i for i in range(4) if i != CAMARA]
    for idx in indices:
        for be, nombre in backends:
            cap = cv2.VideoCapture(idx, be)
            if cap.isOpened():
                ok = False
                for _ in range(10):
                    ok, _f = cap.read()
                    if ok:
                        break
                    time.sleep(0.1)
                if ok:
                    print(f"Cámara abierta: índice {idx}, {nombre}")
                    return cap
            cap.release()
    return None


def zona_util(frame):
    """Algunos drivers devuelven la imagen en una esquina y el resto en negro: se recorta."""
    h, w = frame.shape[:2]
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    filas = np.where(gris.max(axis=1) > 8)[0]
    cols = np.where(gris.max(axis=0) > 8)[0]
    if len(filas) == 0 or len(cols) == 0:
        return 0, 0, w, h
    y0, y1, x0, x1 = filas[0], filas[-1] + 1, cols[0], cols[-1] + 1
    if (x1 - x0) * (y1 - y0) < 0.9 * w * h:
        print(f"Imagen útil de la cámara: {x1 - x0}x{y1 - y0} (se recorta el borde negro)")
        return x0, y0, x1, y1
    print(f"Resolución de la cámara: {w}x{h}")
    return 0, 0, w, h


# ==================== Bucle principal ====================
def main():
    global ultimo_frame, armado, descartadas
    cap = abrir_camara()
    if cap is None:
        print("\nERROR: no se pudo abrir ninguna cámara.")
        print("  1) Lo más común: la cámara la está usando otro programa.")
        print("     sistema_seguridad.py corre en segundo plano SIN ventana: ciérralo.")
        print("     En PowerShell:  Get-Process python   (y ciérralos con Stop-Process -Id <número>)")
        print("     Cierra también Teams, Zoom, Discord, OBS o la app Cámara si están abiertos.")
        print("  2) Revisa que la cámara esté conectada.")
        return
    for _ in range(5):
        cap.read()

    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow(VENTANA, W, H)
    completa = False
    contador, prev = 0, None
    ultima_conf, ultima_alerta = None, 0.0
    t_prev, fps, fallos = time.time(), 0.0, 0
    recorte = None

    while True:
        ok, frame = cap.read()
        if not ok:
            fallos += 1
            if fallos > 50:
                print("ERROR: la cámara dejó de mandar imagen.")
                break
            time.sleep(0.05)
            continue
        fallos = 0
        if recorte is None:
            recorte = zona_util(frame)
        x0, y0, x1, y1 = recorte
        frame = frame[y0:y1, x0:x1]
        with lock_frame:
            ultimo_frame = frame.copy()

        probs = predecir(frame)
        idx = int(np.argmax(probs))
        clase, conf, tipo = clases[idx], float(probs[idx]), TIPOS[idx]

        # Filtro: misma clase, con confianza >= umbral, FRAMES imagenes seguidas
        if conf >= UMBRAL and clase == prev:
            contador += 1
        else:
            # una racha de persona que se corto antes de confirmar = deteccion descartada
            if prev is not None and TIPOS[clases.index(prev)] != "vacio" and 0 < contador < FRAMES:
                descartadas += 1
            contador, prev = (1, clase) if conf >= UMBRAL else (0, None)

        espera = 0.0
        if contador >= FRAMES and clase != ultima_conf:
            restante = COOLDOWN_DEMO_S - (time.time() - ultima_alerta)
            if tipo == "vacio" or restante <= 0:
                actuar(tipo, frame, conf)
                ultima_conf = clase
                if tipo != "vacio":
                    ultima_alerta = time.time()
            else:
                espera = restante

        ahora = time.time()
        fps = 0.9 * fps + 0.1 / max(ahora - t_prev, 1e-3)
        t_prev = ahora

        cv2.imshow(VENTANA, dibujar(frame, probs, tipo, conf, contador, espera, fps))
        k = cv2.waitKey(1) & 0xFF
        if k in (ord("q"), 27):
            break
        if k == ord("f"):
            completa = not completa
            cv2.setWindowProperty(VENTANA, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if completa else cv2.WINDOW_NORMAL)
        elif k == ord("a"):
            armado = not armado
            evento("Sistema ARMADO" if armado else "Sistema DESARMADO", VERDE_L if armado else GRIS)
            en_hilo(telegram, "🔔 Sistema ARMADO (red + cámara)." if armado else "🔕 Sistema DESARMADO.")
        elif k == ord("r"):
            contador, prev, ultima_conf, ultima_alerta = 0, None, None, 0.0
            evento("Detección reiniciada", GRIS)
        try:
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break
        except cv2.error:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    print(f"Configuración leída de: {ORIGEN_CFG}")
    _c = {}
    cargar_json(ARCHIVO_CONOCIDOS, _c)
    CONOCIDOS.update({k.lower(): v for k, v in _c.items()})
    cargar_json(ARCHIVO_DIARIO, diario)
    evento(f"Sistema iniciado · umbral {UMBRAL:.0%} · {FRAMES} imágenes", AMBAR_L)
    en_hilo(telegram_menu, "✅ Sistema de seguridad iniciado (cámara + red). Usa los botones o /ayuda.")
    threading.Thread(target=hilo_telegram, daemon=True).start()
    threading.Thread(target=hilo_red, daemon=True).start()
    threading.Thread(target=hilo_resumen, daemon=True).start()
    try:
        main()
    except KeyboardInterrupt:
        pass
    telegram("🛑 Sistema detenido.")
    print("Listo.")
