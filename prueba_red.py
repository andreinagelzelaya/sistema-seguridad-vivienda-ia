"""
============================================================
PRUEBA DEL MONITOR DE RED (datos para el paper)
============================================================
Mide con datos REALES:
  1. Duracion de cada escaneo y cantidad de equipos detectados.
  2. Tiempo que tarda en detectar que tu celular SE DESCONECTA.
  3. Tiempo que tarda en detectar que tu celular SE CONECTA.

Usa la MISMA logica del sistema (ping + tabla ARP, UMBRAL_AUSENCIA).

Como se usa (solo en TU red de casa):
  - python prueba_red.py
  - Elige tu celular de la lista.
  - En cada ensayo: apaga/prende el WiFi del celular y
    presiona Enter en ese mismo instante.

Todo se guarda en la carpeta  resultados/
============================================================
"""

import os
import sys
import csv
import time
import socket
import platform
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

try:
    import config as cfg
except ImportError:
    print("ERROR: no existe config.py en esta carpeta.")
    sys.exit(1)

import requests

N_ENSAYOS_DEFECTO = 10
N_ESCANEOS_BASE = 10
TIMEOUT_S = 300
ES_WINDOWS = platform.system() == "Windows"
CREATE_NO_WINDOW = 0x08000000 if ES_WINDOWS else 0
CARPETA = "resultados"
os.makedirs(CARPETA, exist_ok=True)
SELLO = datetime.now().strftime("%Y%m%d_%H%M")
escaneos = []


# ==================== Misma logica del sistema ====================
def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def ping(ip):
    cmd = (["ping", "-n", "1", "-w", "1000", ip] if ES_WINDOWS
           else ["ping", "-c", "1", "-W", "1", ip])
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=CREATE_NO_WINDOW)


def leer_arp(subred):
    disp, prefijo = {}, subred + "."
    if ES_WINDOWS:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW).stdout
        for linea in out.splitlines():
            p = linea.split()
            if len(p) >= 2 and p[1].count("-") == 5 and p[0].startswith(prefijo):
                mac = p[1].replace("-", ":").lower()
                if int(mac.split(":")[0], 16) & 0x01:
                    continue
                disp[mac] = p[0]
    else:
        out = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True).stdout
        for linea in out.splitlines():
            p = linea.split()
            if ("lladdr" in p and p[-1] in ("REACHABLE", "DELAY", "PROBE")
                    and p[0].startswith(prefijo)):
                disp[p[p.index("lladdr") + 1].lower()] = p[0]
    return disp


def escanear(subred, etapa):
    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=64) as ex:
        list(ex.map(ping, [f"{subred}.{i}" for i in range(1, 255)]))
    disp = leer_arp(subred)
    dur = time.perf_counter() - t
    escaneos.append({"etapa": etapa, "duracion_s": round(dur, 3), "equipos": len(disp)})
    return disp, dur


def fabricante(mac):
    try:
        if int(mac.split(":")[0], 16) & 0x02:
            return "MAC aleatoria"
        r = requests.get(f"https://api.macvendors.com/{mac}", timeout=5)
        return r.text.strip() if r.status_code == 200 else "desconocido"
    except Exception:
        return "desconocido"


# ==================== Ensayos ====================
def esperar(subred, mac, quiere_presente, t0):
    """Escanea igual que el sistema hasta detectar el cambio. Devuelve (segundos, escaneos)."""
    misses, n = 0, 0
    while time.perf_counter() - t0 < TIMEOUT_S:
        disp, _ = escanear(subred, "ensayo")
        n += 1
        presente = mac in disp
        if quiere_presente and presente:
            return time.perf_counter() - t0, n
        if not quiere_presente:
            misses = 0 if presente else misses + 1
            if misses >= cfg.UMBRAL_AUSENCIA:
                return time.perf_counter() - t0, n
        time.sleep(cfg.INTERVALO_S)
    return None, n


def main():
    try:
        subred = ".".join(ip_local().split(".")[:3])
    except Exception:
        print("ERROR: sin conexion a la red.")
        return
    if subred not in cfg.REDES_CASA:
        print(f"Red actual {subred}.x no esta en REDES_CASA. Por seguridad solo se prueba en tu red.")
        return
    print(f"Red: {subred}.0/24   UMBRAL_AUSENCIA={cfg.UMBRAL_AUSENCIA}   INTERVALO_S={cfg.INTERVALO_S}")

    # 1) Escaneos base
    print(f"\nHaciendo {N_ESCANEOS_BASE} escaneos de referencia...")
    ultimo = {}
    for i in range(N_ESCANEOS_BASE):
        ultimo, dur = escanear(subred, "base")
        print(f"  escaneo {i + 1}: {dur:.2f} s, {len(ultimo)} equipos")
        time.sleep(cfg.INTERVALO_S)

    # 2) Elegir el celular
    print("\nEquipos detectados ahora:")
    lista = sorted(ultimo.items(), key=lambda x: int(x[1].split(".")[-1]))
    for n, (mac, ip) in enumerate(lista, 1):
        print(f"  {n:>2}. {ip:<15} {mac}  {fabricante(mac)}")
        time.sleep(1.1)  # limite de la API de fabricantes
    eleccion = input("\nNumero de TU celular (o escribe su MAC): ").strip().lower()
    mac = lista[int(eleccion) - 1][0] if eleccion.isdigit() else eleccion
    print(f"Celular elegido: {mac}")
    n_ens = input(f"¿Cuantos ensayos? [Enter = {N_ENSAYOS_DEFECTO}]: ").strip()
    n_ens = int(n_ens) if n_ens.isdigit() else N_ENSAYOS_DEFECTO

    # 3) Ensayos desconexion / conexion
    ensayos = []
    for i in range(1, n_ens + 1):
        for accion, presente in (("desconexion", False), ("conexion", True)):
            verbo = "APAGA" if not presente else "PRENDE"
            input(f"\nEnsayo {i}/{n_ens} - {verbo} el WiFi del celular y presiona Enter en ese instante...")
            t0 = time.perf_counter()
            seg, n = esperar(subred, mac, presente, t0)
            ensayos.append({"ensayo": i, "evento": accion,
                            "segundos": round(seg, 2) if seg is not None else "",
                            "detectado": seg is not None, "escaneos": n})
            print(f"  {accion}: " + (f"detectada en {seg:.1f} s ({n} escaneos)" if seg is not None
                                     else f"NO detectada en {TIMEOUT_S} s"))
            if presente:
                time.sleep(5)  # que el celular se estabilice

    # 4) Guardar y resumir
    for nombre, filas in ((f"red_ensayos_{SELLO}.csv", ensayos), (f"red_escaneos_{SELLO}.csv", escaneos)):
        with open(os.path.join(CARPETA, nombre), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
            w.writeheader()
            w.writerows(filas)

    L = [f"RESUMEN PRUEBA DE RED - {SELLO}",
         f"Red {subred}.0/24 | UMBRAL_AUSENCIA={cfg.UMBRAL_AUSENCIA} | INTERVALO_S={cfg.INTERVALO_S}"]
    d = [e["duracion_s"] for e in escaneos]
    q = [e["equipos"] for e in escaneos]
    L.append(f"Escaneos: {len(d)} | duracion media {sum(d) / len(d):.2f} s "
             f"(min {min(d):.2f}, max {max(d):.2f}) | equipos media {sum(q) / len(q):.1f} "
             f"(min {min(q)}, max {max(q)})")
    for ev in ("desconexion", "conexion"):
        v = [e["segundos"] for e in ensayos if e["evento"] == ev and e["detectado"]]
        tot = sum(1 for e in ensayos if e["evento"] == ev)
        if v:
            L.append(f"{ev}: detectadas {len(v)}/{tot} | media {sum(v) / len(v):.1f} s "
                     f"| min {min(v):.1f} | max {max(v):.1f}")
        else:
            L.append(f"{ev}: detectadas 0/{tot}")
    resumen = "\n".join(L)
    with open(os.path.join(CARPETA, f"red_resumen_{SELLO}.txt"), "w", encoding="utf-8") as f:
        f.write(resumen)
    print("\n" + resumen + f"\n\nListo. Archivos en la carpeta '{CARPETA}'.")


if __name__ == "__main__":
    main()
