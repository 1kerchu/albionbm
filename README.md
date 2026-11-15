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
5. Para lo que no hayas visto, pulsa **⟳ Actualizar precios** (ver abajo).
6. Haz **doble clic** en una fila para copiar el nombre del objeto y pegarlo en el buscador del mercado.

Los precios se guardan en `%APPDATA%\AlbionBM\precios.sqlite3`, así que no se pierden al cerrar.

## Todos los precios con un botón

**⟳ Actualizar precios** descarga de la API de Albion Online Data Project los precios de **todas las
ciudades marcadas y del Mercado Negro** para todo lo que marquen los filtros (categorías, tiers,
encantamientos y calidades). También descarga cuántas unidades compra el Mercado Negro al día
(media de los últimos 7 días). Con los filtros por defecto (unos 1.500 objetos) tarda alrededor de un minuto.

- Marca **Auto cada N min** para que se actualice sola (mínimo 5 minutos, para respetar la API).
- La API la alimentan los jugadores, así que algunos precios pueden tener horas. Revisa la columna «Datos».
- La API no dice cuántas unidades hay en cada orden. Por eso, cuando no hay datos leídos del juego, las
  unidades se **estiman** con el volumen diario del Mercado Negro y se marcan con «~».
- Lo que leas en el juego tiene prioridad si es más reciente, y trae cantidades reales.
- La app **no** recorre los mercados del juego por ti: automatizar el juego es botting y lleva a baneo.
  Además, el juego solo enseña el mercado de la ciudad donde estás.

## Preguntarle a Claude en qué invertir

1. Pulsa **⟳ Actualizar precios** y, si quieres más precisión, lee mercados en el juego.
2. Escribe tu dinero en **Capital** (por ejemplo `25000000`) y ajusta los filtros.
3. Pulsa **Exportar para Claude**. El informe se copia al portapapeles y se guarda en
   `Documentos\AlbionBM\informe_albionbm_FECHA.md`.
4. Pégalo (Ctrl+V) o adjunta el archivo en una conversación con Claude y pregunta, por ejemplo:
   *«Tengo 25 millones, ¿en qué me vale más la pena invertir?»*

El informe incluye instrucciones para el asistente, tu configuración (servidor, prémium, impuestos), un
reparto automático propuesto por la app y hasta 150 oportunidades con:
- precio de compra y lo que paga el Mercado Negro;
- **unidades disponibles con beneficio**, inversión máxima y beneficio total, calculados con la
  profundidad de órdenes leída del juego;
- peso por unidad, antigüedad de los datos y origen (juego o API).

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
| `albionbm/calc.py` | Cálculo de oportunidades, unidades disponibles y reparto del capital |
| `albionbm/export.py` | Informe en Markdown para pegárselo a Claude |
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
