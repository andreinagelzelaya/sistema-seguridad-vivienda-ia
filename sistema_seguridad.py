"""
============================================================
SISTEMA DE SEGURIDAD INTELIGENTE - TODO EN UNO
============================================================
Un solo programa que corre junto:

  - CAMARA + IA (Teachable Machine): Vacio / Andrei / Externo
        Vacio   -> nada
        Andrei  -> "Bienvenido Andrei"
        Externo -> foto + Telegram con botones (conocido/desconocido)
        Con capa de verificacion: 10 frames seguidos con conf >= 0.90,
        aviso solo al cambiar la clase confirmada y 90 s entre alertas.

  - MONITOR DE RED (solo en tu casa): avisa conexiones/desconexiones.

  - COMANDOS por Telegram: /foto /video /estado /diario /armar /desarmar
        /historial /resumen /semana /exportar /agregar /quitar /conocidos /silencio

  - Resumen diario y semanal automatico.

/armar y /desarmar controlan TODO (red + camara).
Configuracion en config.py (no se sube a GitHub). Corre sin ventana: Ctrl+C para detener.
============================================================
"""

import os
os.environ["TF_USE_LEGACY_KERAS"] = "1"

import subprocess
import socket
import time
import threading
import json
import platform
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import requests
from tf_keras.models import load_model
from tf_keras.layers import DepthwiseConv2D

ES_WINDOWS = platform.system() == "Windows"
CREATE_NO_WINDOW = 0x08000000 if ES_WINDOWS else 0
BACKEND_CAM = cv2.CAP_DSHOW if ES_WINDOWS else cv2.CAP_ANY

# ==================== CONFIGURACION ====================
# Todo se lee de config.py: el mismo archivo que usan sistema_seguridad_demo.py,
# prueba_camara.py y prueba_red.py. Asi el sistema y las pruebas del articulo
# usan exactamente los mismos parametros, y el token no queda en el codigo
# (config.py esta en .gitignore).
try:
    import config as cfg
except ImportError:
    raise SystemExit("ERROR: falta config.py (copia config_ejemplo.py como config.py y llenalo).")

TOKEN   = str(cfg.TOKEN)
CHAT_ID = str(cfg.CHAT_ID)
ARCHIVO_MODELO = cfg.ARCHIVO_MODELO
ARCHIVO_LABELS = cfg.ARCHIVO_LABELS
CLASE_VACIO   = cfg.CLASE_VACIO.lower()
CLASE_DUENO   = cfg.CLASE_DUENO.lower()
CLASE_EXTERNO = cfg.CLASE_EXTERNO.lower()
NOMBRE_DUENO  = cfg.NOMBRE_DUENO

CAMARA           = cfg.CAMARA
UMBRAL_CONFIANZA = cfg.UMBRAL_CONFIANZA    # 0.90
FRAMES_CONFIRMA  = cfg.FRAMES_CONFIRMA     # 10 frames seguidos, TODOS con conf >= umbral
COOLDOWN_CAM_S   = cfg.COOLDOWN_CAM_S      # 90 s entre alertas de camara
SEGUNDOS_VIDEO   = cfg.SEGUNDOS_VIDEO_EVIDENCIA   # 8 s

VIGILAR_RED     = cfg.VIGILAR_RED
REDES_CASA      = list(cfg.REDES_CASA)
INTERVALO_S     = cfg.INTERVALO_S          # pausa de 3 s entre barridos
UMBRAL_AUSENCIA = cfg.UMBRAL_AUSENCIA      # 3 barridos sin respuesta = desconectado
HORA_RESUMEN    = cfg.HORA_RESUMEN

# Dispositivos con nombre: los de config.py + los agregados con /agregar (conocidos.json)
CONOCIDOS = {k.lower(): v for k, v in cfg.CONOCIDOS.items()}
# =======================================================

API = f"https://api.telegram.org/bot{TOKEN}"
CARPETA = "evidencia"
os.makedirs(CARPETA, exist_ok=True)

ARCHIVO_HISTORIAL = "historial.csv"
ARCHIVO_CONOCIDOS = "conocidos.json"
ARCHIVO_DIARIO    = "diario.json"

lock = threading.Lock()
lock_frame = threading.Lock()
armado = True
historial = []
rastreo = {}
diario = {}
offset_tg = 0
silencio_hasta = 0.0
ultimo_frame = None        # ultimo frame de la camara (compartido)


# Parche para el modelo de Teachable Machine
class DepthwiseConv2DCompat(DepthwiseConv2D):
    def __init__(self, *args, **kwargs):
        kwargs.pop("groups", None)
        super().__init__(*args, **kwargs)


print("Cargando modelo de Teachable Machine...")
modelo = load_model(ARCHIVO_MODELO, compile=False,
                    custom_objects={"DepthwiseConv2D": DepthwiseConv2DCompat})
with open(ARCHIVO_LABELS, encoding="utf-8") as f:
    clases = [l.strip() for l in f if l.strip()]
clases = [c.split(" ", 1)[1] if " " in c else c for c in clases]
print("Clases:", clases)


# ==================== Telegram ====================
def telegram(texto):
    try:
        requests.post(f"{API}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": texto}, timeout=10)
    except Exception as e:
        print("Error Telegram:", e)


def teclado():
    return {"keyboard": [
        ["📸 Foto", "🎥 Video"],
        ["📊 Estado", "📖 Diario", "📅 Resumen"],
        ["🔔 Armar", "🔇 Desarmar", "🔕 Silencio 1h"],
        ["❓ Ayuda"],
    ], "resize_keyboard": True}


def telegram_menu(texto):
    try:
        requests.post(f"{API}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": texto, "reply_markup": teclado()},
                      timeout=10)
    except Exception as e:
        print("Error Telegram:", e)


BOTONES = {
    "📸 Foto": "/foto", "🎥 Video": "/video", "📊 Estado": "/estado",
    "📖 Diario": "/diario", "📅 Resumen": "/resumen", "🔔 Armar": "/armar",
    "🔇 Desarmar": "/desarmar", "🔕 Silencio 1h": "/silencio 1h", "❓ Ayuda": "/ayuda",
}


def enviar_foto(ruta, caption=""):
    try:
        with open(ruta, "rb") as f:
            requests.post(f"{API}/sendPhoto",
                          data={"chat_id": CHAT_ID, "caption": caption},
                          files={"photo": f}, timeout=20)
    except Exception as e:
        print("Error foto:", e)


def enviar_foto_botones(ruta, caption):
    teclado_ib = {"inline_keyboard": [[
        {"text": "✅ Es conocido", "callback_data": "ok"},
        {"text": "🚨 Desconocido", "callback_data": "no"},
    ]]}
    try:
        with open(ruta, "rb") as f:
            requests.post(f"{API}/sendPhoto",
                          data={"chat_id": CHAT_ID, "caption": caption,
                                "reply_markup": json.dumps(teclado_ib)},
                          files={"photo": f}, timeout=20)
    except Exception as e:
        print("Error foto botones:", e)


def enviar_video(ruta, caption=""):
    try:
        with open(ruta, "rb") as f:
            requests.post(f"{API}/sendVideo",
                          data={"chat_id": CHAT_ID, "caption": caption},
                          files={"video": f}, timeout=60)
    except Exception as e:
        print("Error video:", e)


def enviar_documento(ruta):
    try:
        with open(ruta, "rb") as f:
            requests.post(f"{API}/sendDocument",
                          data={"chat_id": CHAT_ID}, files={"document": f}, timeout=30)
    except Exception:
        telegram("No pude exportar el historial (¿aun no hay eventos?).")


# ==================== utilidades ====================
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
    return (f"📊 Resumen del dia\nConexiones: {conex}\nDesconexiones: {desc}\n"
            f"Eventos de camara: {cam}\nEventos totales: {len(hoy)}")


def leer_eventos_desde(dias):
    from datetime import timedelta
    limite = datetime.now() - timedelta(days=dias)
    eventos = []
    try:
        with open(ARCHIVO_HISTORIAL, encoding="utf-8") as f:
            for linea in f:
                p = linea.strip().split(",", 2)
                if len(p) >= 2:
                    try:
                        t = datetime.strptime(p[0], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                    if t >= limite:
                        eventos.append((t, p[1]))
    except Exception:
        pass
    return eventos


def resumen_semanal_texto():
    ev = leer_eventos_desde(7)
    conex = sum(1 for _, tipo in ev if tipo == "conexion")
    desc = sum(1 for _, tipo in ev if tipo == "desconexion")
    return (f"📅 Resumen semanal (7 dias)\nConexiones: {conex}\n"
            f"Desconexiones: {desc}\nEventos totales: {len(ev)}")


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


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def ping(ip):
    cmd = ["ping", "-n", "1", "-w", "1000", ip] if ES_WINDOWS else ["ping", "-c", "1", "-W", "1", ip]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=CREATE_NO_WINDOW)


def barrer_red(subred):
    ips = [f"{subred}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=64) as ex:
        list(ex.map(ping, ips))


def leer_arp(subred):
    """Solo equipos de la subred de la casa (ignora otras interfaces, p. ej. VirtualBox)."""
    disp = {}
    if ES_WINDOWS:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW).stdout
        for linea in out.splitlines():
            p = linea.split()
            if len(p) >= 2 and p[1].count("-") == 5 and p[0].startswith(subred + "."):
                mac = p[1].replace("-", ":").lower()
                try:
                    if int(mac.split(":")[0], 16) & 0x01:
                        continue
                except Exception:
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
        time.sleep(1.1)   # la API gratuita admite 1 consulta por segundo
        return r.text.strip() if (r.status_code == 200 and r.text.strip()) else "desconocido"
    except Exception:
        return "desconocido"


def hostname(ip):
    try:
        socket.setdefaulttimeout(2)
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""
    finally:
        socket.setdefaulttimeout(None)


def duracion(delta):
    seg = int(delta.total_seconds())
    h = seg // 3600
    m = (seg % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"


def parse_tiempo(s):
    s = s.lower().strip()
    try:
        if s.endswith("h"):
            return int(float(s[:-1]) * 60)
        if s.endswith("m"):
            return int(s[:-1])
        return int(s)
    except Exception:
        return 0


def en_silencio():
    return time.time() < silencio_hasta


# ==================== Camara / foto ====================
def clasificar(frame):
    img = cv2.resize(frame, (224, 224))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
    arr = np.expand_dims((img / 127.5) - 1.0, axis=0)
    pred = np.array(modelo(arr, training=False))[0]   # llamada directa: ~60 ms (predict() es mas lento)
    idx = int(np.argmax(pred))
    return clases[idx], float(pred[idx])


def guardar_foto(frame, nota=""):
    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f = frame.copy()
    cv2.putText(f, hora, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    if nota:
        cv2.putText(f, nota, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    ruta = os.path.join(CARPETA, datetime.now().strftime("%Y%m%d_%H%M%S") + ".jpg")
    cv2.imwrite(ruta, f)
    return ruta


def frame_actual():
    with lock_frame:
        return None if ultimo_frame is None else ultimo_frame.copy()


def grabar_video(segundos=5):
    frame = frame_actual()
    if frame is None:
        return None
    h, w = frame.shape[:2]
    ruta = os.path.join(CARPETA, datetime.now().strftime("%Y%m%d_%H%M%S") + ".mp4")
    out = cv2.VideoWriter(ruta, cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    fin = time.time() + segundos
    while time.time() < fin:
        f = frame_actual()
        if f is not None:
            out.write(f)
        time.sleep(0.1)
    out.release()
    return ruta


# ==================== comandos ====================
def manejar_comando(texto):
    global armado, silencio_hasta
    partes = texto.strip().split()
    if not partes:
        return
    cmd = partes[0].lower().split("@")[0]
    args = partes[1:]

    if cmd in ("/ayuda", "/start", "/help", "/menu"):
        telegram_menu("Comandos:\n/foto  /video  /estado  /diario\n"
                      "/armar  /desarmar  /silencio 2h\n"
                      "/historial  /resumen  /semana  /exportar\n"
                      "/agregar MAC nombre  /quitar MAC  /conocidos")
    elif cmd == "/armar":
        armado = True
        telegram("🔔 Sistema ARMADO (red + camara).")
    elif cmd == "/desarmar":
        armado = False
        telegram("🔕 Sistema DESARMADO.")
    elif cmd == "/foto":
        ruta = guardar_foto(frame_actual(), "Foto por comando") if frame_actual() is not None else None
        if ruta:
            enviar_foto(ruta, "Foto en vivo")
        else:
            telegram("No hay imagen de la camara.")
    elif cmd == "/video":
        telegram("🎥 Grabando 5 segundos...")
        ruta = grabar_video(5)
        enviar_video(ruta, "Video en vivo") if ruta else telegram("No hay imagen de la camara.")
    elif cmd == "/estado":
        with lock:
            actuales = dict(rastreo)
        if not actuales:
            telegram("No hay datos de red (¿estas en casa?).")
        else:
            lineas = ["📡 Conectados ahora:"]
            for mac, info in actuales.items():
                lineas.append(f"• {CONOCIDOS.get(mac, info.get('fab', 'desconocido'))} ({mac})")
            telegram("\n".join(lineas))
    elif cmd == "/diario":
        if not diario:
            telegram("Aun no hay registro de entradas/salidas.")
        else:
            lineas = ["📖 Diario:"]
            for mac, d in diario.items():
                nombre = CONOCIDOS.get(mac, mac)
                lleg = d.get("llegada", "")[11:16] or "-"
                sal = d.get("salida", "")[11:16] or "-"
                lineas.append(f"• {nombre}: llegada {lleg} | salida {sal}")
            telegram("\n".join(lineas))
    elif cmd == "/historial":
        with lock:
            ultimos = historial[-10:]
        if not ultimos:
            telegram("Sin eventos aun.")
        else:
            lineas = ["🗒️ Ultimos eventos:"]
            for h in ultimos:
                lineas.append(f"• {h['t'].strftime('%H:%M')} {h['tipo']}: {h['detalle']}")
            telegram("\n".join(lineas))
    elif cmd == "/resumen":
        telegram(resumen_texto())
    elif cmd == "/semana":
        telegram(resumen_semanal_texto())
    elif cmd == "/exportar":
        enviar_documento(ARCHIVO_HISTORIAL)
    elif cmd == "/silencio":
        if args and parse_tiempo(args[0]) > 0:
            m = parse_tiempo(args[0])
            silencio_hasta = time.time() + m * 60
            telegram(f"🔕 Silenciado por {m} min.")
        else:
            telegram("Uso: /silencio 2h  o  /silencio 30m")
    elif cmd == "/agregar":
        if len(args) >= 2:
            CONOCIDOS[args[0].lower()] = " ".join(args[1:])
            guardar_json(ARCHIVO_CONOCIDOS, CONOCIDOS)
            telegram(f"✅ Agregado: {' '.join(args[1:])} ({args[0].lower()})")
        else:
            telegram("Uso: /agregar MAC nombre")
    elif cmd == "/quitar":
        if args and CONOCIDOS.pop(args[0].lower(), None) is not None:
            guardar_json(ARCHIVO_CONOCIDOS, CONOCIDOS)
            telegram(f"🗑️ Quitado: {args[0].lower()}")
        else:
            telegram("Esa MAC no estaba, o falta la MAC.")
    elif cmd == "/conocidos":
        if not CONOCIDOS:
            telegram("No hay conocidos registrados.")
        else:
            telegram("👥 Conocidos:\n" + "\n".join(f"• {n} ({m})" for m, n in CONOCIDOS.items()))
    else:
        telegram("No conozco ese comando. Usa /ayuda")


# ==================== hilos ====================
def hilo_telegram():
    global offset_tg
    try:
        r = requests.get(f"{API}/getUpdates", timeout=10).json()
        if r.get("result"):
            offset_tg = r["result"][-1]["update_id"] + 1
    except Exception:
        pass
    while True:
        try:
            r = requests.get(f"{API}/getUpdates",
                             params={"offset": offset_tg, "timeout": 20}, timeout=30).json()
        except Exception:
            time.sleep(2)
            continue
        for upd in r.get("result", []):
            offset_tg = upd["update_id"] + 1
            origen = (upd.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
                      or upd.get("message", {}).get("chat", {}).get("id"))
            if str(origen) != CHAT_ID:
                continue   # solo obedece al chat del propietario (nadie mas pide /foto o /video)
            if "callback_query" in upd:
                cq = upd["callback_query"]
                try:
                    requests.post(f"{API}/answerCallbackQuery",
                                  json={"callback_query_id": cq["id"]}, timeout=10)
                except Exception:
                    pass
                data = cq.get("data", "")
                if data == "ok":
                    telegram("✅ Marcado como conocido. Sin alarma.")
                    log("respuesta", "conocido")
                elif data == "no":
                    telegram("🚨 DESCONOCIDO confirmado. Grabando evidencia...")
                    log("respuesta", "DESCONOCIDO")
                    ruta = grabar_video(SEGUNDOS_VIDEO)   # 8 s de evidencia
                    if ruta:
                        enviar_video(ruta, "📹 Evidencia del desconocido")
                    else:
                        telegram("No pude grabar el video (¿camara activa?).")
                continue
            texto = upd.get("message", {}).get("text", "")
            if texto in BOTONES:
                manejar_comando(BOTONES[texto])
            elif texto.startswith("/"):
                manejar_comando(texto)


def hilo_red():
    try:
        subred = ".".join(ip_local().split(".")[:3])
    except Exception:
        print("Sin red: vigilancia de red DESACTIVADA.")
        return
    if not VIGILAR_RED:
        print("Vigilancia de red desactivada en config.py.")
        return
    if subred not in REDES_CASA:
        print(f"Red actual ({subred}.x) no es la de casa. Vigilancia de red DESACTIVADA.")
        return
    print("Vigilancia de red ACTIVA.")
    local = {}
    primera = True
    while True:
        try:
            barrer_red(subred)
            disp = leer_arp(subred)
        except Exception:
            time.sleep(INTERVALO_S)
            continue
        actuales = set(disp.keys())

        if primera:
            for mac in actuales:
                local[mac] = {"ip": disp[mac], "fab": fabricante(mac), "misses": 0}
            primera = False
            with lock:
                rastreo.clear(); rastreo.update(local)
            time.sleep(INTERVALO_S)
            continue

        for mac in actuales:
            if mac not in local:
                fab = fabricante(mac)
                local[mac] = {"ip": disp[mac], "fab": fab, "misses": 0}
                hora = datetime.now().strftime("%H:%M:%S")
                nombre = CONOCIDOS.get(mac)
                if nombre:
                    ahora_dt = datetime.now()
                    d = diario.get(mac, {})
                    txt = f"👋 ¡Bienvenido {nombre}! Llegaste a casa."
                    if d.get("salida"):
                        try:
                            txt += f"\nEstuviste fuera: {duracion(ahora_dt - datetime.fromisoformat(d['salida']))}"
                        except Exception:
                            pass
                    d["llegada"] = ahora_dt.isoformat()
                    diario[mac] = d
                    guardar_json(ARCHIVO_DIARIO, diario)
                    txt += f"\nHora: {hora}"
                    log("conexion", nombre)
                else:
                    host = hostname(disp[mac])
                    extra = f"\nNombre: {host}" if host else ""
                    txt = (f"🟢 Dispositivo CONECTADO\nFabricante: {fab}{extra}\n"
                           f"MAC: {mac}\nIP: {disp[mac]}\nHora: {hora}")
                    log("conexion", f"{fab} {mac}")
                if armado and not en_silencio():
                    telegram(txt)
            else:
                local[mac]["misses"] = 0
                local[mac]["ip"] = disp[mac]

        for mac in list(local.keys()):
            if mac not in actuales:
                local[mac]["misses"] += 1
                if local[mac]["misses"] >= UMBRAL_AUSENCIA:
                    info = local.pop(mac)
                    hora = datetime.now().strftime("%H:%M:%S")
                    nombre = CONOCIDOS.get(mac)
                    if nombre:
                        ahora_dt = datetime.now()
                        d = diario.get(mac, {})
                        txt = f"👋 Hasta luego {nombre}, que te vaya bien."
                        if d.get("llegada"):
                            try:
                                txt += f"\nEstuvo en casa: {duracion(ahora_dt - datetime.fromisoformat(d['llegada']))}"
                            except Exception:
                                pass
                        d["salida"] = ahora_dt.isoformat()
                        diario[mac] = d
                        guardar_json(ARCHIVO_DIARIO, diario)
                        txt += f"\nHora: {hora}"
                        log("desconexion", nombre)
                    else:
                        txt = f"🔴 Dispositivo DESCONECTADO\nFabricante: {info['fab']}\nMAC: {mac}\nHora: {hora}"
                        log("desconexion", f"{info['fab']} {mac}")
                    if armado and not en_silencio():
                        telegram(txt)

        with lock:
            rastreo.clear(); rastreo.update(local)
        time.sleep(INTERVALO_S)


def hilo_resumen():
    ultimo_dia = None
    ultimo_sem = None
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


# ==================== camara (hilo principal) ====================
def actuar_camara(clase_l, frame):
    if not (armado and not en_silencio()):
        return
    if clase_l == CLASE_DUENO:
        telegram(f"👋 ¡Bienvenido {NOMBRE_DUENO}! (camara)")
        log("camara", NOMBRE_DUENO)
        print(f"CAMARA: {NOMBRE_DUENO}")
    elif clase_l == CLASE_EXTERNO:
        ruta = guardar_foto(frame, "Externo detectado")
        enviar_foto_botones(ruta, "⚠️ Persona detectada en la entrada. ¿La reconoces?")
        log("camara", "Externo")
        print("CAMARA: Externo -> foto + botones")


def bucle_camara():
    global ultimo_frame
    cap = cv2.VideoCapture(CAMARA, BACKEND_CAM)
    if not cap.isOpened():
        print("No se pudo abrir la camara.")
        return
    for _ in range(5):
        cap.read()
        time.sleep(0.1)

    contador = 0
    clase_prev = None
    ultima_confirmada = None
    ultima_alerta = 0.0

    # Corre en SEGUNDO PLANO (sin ventana). Para detener: Ctrl+C en la terminal.
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1)
            continue

        with lock_frame:
            ultimo_frame = frame.copy()

        clase, conf = clasificar(frame)
        clase_l = clase.lower()

        # Capa de verificacion (Ecuacion 2 del articulo): la clase se confirma solo
        # si es la prediccion en FRAMES_CONFIRMA frames seguidos, cada uno con
        # confianza >= UMBRAL_CONFIANZA. Un frame dudoso reinicia la racha.
        if conf >= UMBRAL_CONFIANZA and clase == clase_prev:
            contador += 1
        elif conf >= UMBRAL_CONFIANZA:
            contador, clase_prev = 1, clase
        else:
            contador, clase_prev = 0, None

        confirmada = contador >= FRAMES_CONFIRMA
        if confirmada and clase != ultima_confirmada:
            if clase_l == CLASE_VACIO or (time.time() - ultima_alerta > COOLDOWN_CAM_S):
                actuar_camara(clase_l, frame)
                ultima_confirmada = clase
                if clase_l != CLASE_VACIO:
                    ultima_alerta = time.time()

    cap.release()


# ==================== arranque ====================
print("Iniciando sistema...")
_extra = {}
cargar_json(ARCHIVO_CONOCIDOS, _extra)
CONOCIDOS.update({k.lower(): v for k, v in _extra.items()})
cargar_json(ARCHIVO_DIARIO, diario)
print(f"Config: umbral {UMBRAL_CONFIANZA:.0%} · {FRAMES_CONFIRMA} frames · {COOLDOWN_CAM_S} s entre alertas")
telegram_menu("✅ Sistema de seguridad iniciado (red + camara). Usa los botones o /ayuda.")

threading.Thread(target=hilo_telegram, daemon=True).start()
threading.Thread(target=hilo_red, daemon=True).start()
threading.Thread(target=hilo_resumen, daemon=True).start()

print("Sistema corriendo en segundo plano. Ctrl+C para detener.")
try:
    bucle_camara()          # camara sin ventana (headless)
except KeyboardInterrupt:
    pass
print("Sistema detenido.")