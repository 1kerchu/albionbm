# Albion · Mercado Negro

App de escritorio para **Windows** que **lee los precios directamente del juego** mientras juegas a
Albion Online. Compara lo que cuesta un objeto en el mercado de cada ciudad con lo que paga el
**Mercado Negro** de Caerleon, y ordena las oportunidades por beneficio en porcentaje y en plata.

Las ciudades que no hayas visitado se pueden completar con la API pública de
[Albion Online Data Project](https://www.albion-online-data.com/).

## Cómo lee el juego (y por qué es seguro)

La app **escucha pasivamente** el tráfico de red que el servidor envía a tu juego por el puerto 5056,
igual que el cliente oficial de Albion Online Data Project. Cuando abres un mercado, el servidor manda la
lista de órdenes y la app la lee.

- **No** modifica el juego, **no** lee su memoria, **no** envía nada al servidor y **no** automatiza acciones.
- Sandbox Interactive tolera este tipo de herramientas pasivas (el propio Albion Data Project funciona así).
  Aun así, cualquier herramienta de terceros se usa bajo tu responsabilidad.
- A veces el juego **cifra** los datos de mercado. Si pasa, la app lo avisa y tienes que tirar de la API.

## Instalación

1. Instala **Npcap** (gratis): <https://npcap.com>. En el instalador marca
   *«Install Npcap in WinPcap API-compatible Mode»*.
2. Elige una opción:
   - **Ejecutable:** descarga `AlbionBM.exe` desde la pestaña *Actions* del repositorio
     (último build → *Artifacts* → `AlbionBM-windows`), o genéralo tú con `build_exe.bat`.
   - **Desde el código:** instala Python 3.9+ (<https://python.org>, marca «Add to PATH») y haz doble
     clic en `iniciar.bat`.
3. Si la captura no arranca, prueba a ejecutar la app **como administrador**.

## Cómo se usa

1. Abre la app y luego el juego (o al revés, da igual). Arriba debe poner **● Captura: activa**.
2. Ve al **Mercado Negro** de Caerleon, abre la pestaña **Vender** y navega por las categorías
   (armas, armaduras…). La app guarda lo que paga el Mercado Negro.
3. En cada ciudad, abre el mercado (pestaña **Comprar**) y navega. La app guarda los precios de venta.
4. La tabla se actualiza sola. Las filas en **verde** usan precios leídos de tu juego.
5. Para lo que no hayas visto, pulsa **Completar con la API**.
6. Haz **doble clic** en una fila para copiar el nombre del objeto y pegarlo en el buscador del mercado.

Los precios se guardan en `%APPDATA%\AlbionBM\precios.sqlite3`, así que no se pierden al cerrar.

## Cómo calcula el beneficio

| Concepto | Fórmula |
|---|---|
| Coste (compra directa) | orden de venta más barata en la ciudad |
| Coste (orden de compra) | tu orden de compra × 1,025 (tasa de publicación 2,5 %) |
| Recibes | orden de compra más alta del Mercado Negro × (1 − impuesto): 4 % con prémium, 8 % sin |
| Beneficio | Recibes − Coste |
| % | Beneficio / Coste × 100 |

Una orden del Mercado Negro de calidad Q acepta objetos de calidad Q o superior. Por eso un objeto
«Notable» se compara con la mejor orden Normal, Buena o Notable. La columna «Datos» indica la
antigüedad del precio más viejo de los dos.

## Estructura

| Archivo | Qué hace |
|---|---|
| `albionbm/photon.py` | Decodificador del protocolo de red Photon (Protocol18) del juego |
| `albionbm/game.py` | Ubicación del jugador, servidor y órdenes de mercado a partir de los mensajes |
| `albionbm/capture.py` | Captura pasiva con Scapy + Npcap |
| `albionbm/store.py` | Base de datos local de precios (SQLite) |
| `albionbm/api.py` | Cliente de la API de Albion Online Data Project |
| `albionbm/calc.py` | Cálculo de oportunidades |
| `albionbm/gui.py` | Ventana (Tkinter) |
| `data/items.json` | Objetos que compra el Mercado Negro (T4–T8, nombres en español) |
| `scripts/build_items.py` | Regenera `data/items.json` cuando sale contenido nuevo |

Para regenerar la lista de objetos:

```bash
curl -o items_raw.json https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.json
curl -o items_fmt.json https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.json
python scripts/build_items.py items_raw.json items_fmt.json
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Créditos

El decodificador Photon está adaptado del cliente de
[Albion Online Data Project](https://github.com/ao-data/albiondata-client) (MIT) y de
[AlbionDataAvalonia](https://github.com/JPCodeCraft/AlbionDataAvalonia).
Ver `THIRD_PARTY_NOTICES.md`. No uses este proyecto con fines comerciales.
