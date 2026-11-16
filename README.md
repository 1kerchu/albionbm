# Albion · Comercio y Mercado Negro

App de escritorio para **Windows** que busca dónde ganar plata comerciando en Albion Online.
Descarga los precios de todos los mercados con un botón (API pública de
[Albion Online Data Project](https://www.albion-online-data.com/)) y además **lee los precios
directamente del juego** mientras juegas. Con eso te dice qué comprar, dónde, dónde venderlo y cuánto.

## Qué ofrece

- **Tres estrategias:** ciudad → Mercado Negro, entre ciudades con venta rápida, y entre ciudades
  poniendo orden de venta (más margen, más lento).
- **Más mercancías:** además del equipo, recursos, consumibles, monturas y artefactos para el
  comercio entre ciudades.
- **Filtro de precios trampa:** compara cada precio de venta con la media de la semana y marca con ⚠
  los que la superan en más de 1,6 veces (datos viejos u órdenes falsas).
- **Plan de inversión:** con tu capital, la carga de tu montura y un perfil de riesgo
  (Máximo beneficio, Equilibrado o Seguro), propone qué comprar y la mejor ruta para un solo viaje.
- **Avisos** cuando aparece una oportunidad nueva con tus filtros, con actualización automática.
- **Informe para Claude** para preguntarle en qué invertir.

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

## Estrategias, plan de inversión y perfiles

| Estrategia | Compras | Vendes | Para qué sirve |
|---|---|---|---|
| Ciudad → Mercado Negro | orden de venta más barata de una ciudad | al momento, a las órdenes de compra del Mercado Negro | Equipo. Venta inmediata, pero cruzas zona roja |
| Entre ciudades · venta rápida | igual | al momento, a las órdenes de compra de otra ciudad | Cualquier mercancía. Dinero rápido, márgenes menores |
| Entre ciudades · orden de venta | igual | poniendo tu orden al precio más bajo del destino (impuesto + 2,5 %) | Más margen; puede tardar o no venderse |

**★ Plan de inversión** abre una ventana con el mejor cargamento para cada ruta y el detalle de qué
comprar. Usa «Mi capital», «Carga máx. por viaje» y el perfil:

| Perfil | Máx. por objeto | Parte del volumen diario | Datos | Otros |
|---|--:|--:|---|---|
| Máximo beneficio | 50 % | 100 % | cualquiera | concentra el capital |
| Equilibrado | 25 % | 60 % | hasta 6 h | |
| Seguro | 12 % | 30 % | hasta 2 h | solo objetos con ventas diarias conocidas |

Ningún perfil incluye precios sospechosos (⚠). Las cantidades con «~» son estimaciones a partir de
las ventas diarias; compruébalas en el juego antes de comprar.

## Calculadoras

Botón **🖩 Calculadoras** en Windows y pestaña **Calcular** en la web. Todas pueden traer los precios de
la API con un botón, y cualquier precio se puede corregir a mano.

| Calculadora | Qué hace |
|---|---|
| Comprar o fabricar | Para la cantidad que quieras y sin foco, compara comprar el objeto hecho con fabricarlo, contando que el precio sube al comprar muchas unidades. Dice a partir de cuántas unidades cambia la respuesta |
| Fabricación | Coste de fabricar un objeto con su receta real: materiales, retorno de recursos (ciudad con bonus y foco), tasa del taller, y beneficio al venderlo. Incluye beneficio por punto de foco |
| Refinado | Lo mismo para refinar recursos, con los retornos del refinado |
| Venta manual | Metes precio de compra y de venta: impuestos, tasas, beneficio y precio mínimo para no perder |
| Encantar y mejorar | Coste de subir un objeto de .0 a .1/.2/.3 con runas, almas y reliquias, frente a comprarlo ya mejorado |

Subida de precio en «Comprar o fabricar»: en Windows, si has abierto ese mercado en el juego, se
recorren las órdenes reales (precio y cantidad). Si no, y siempre en la web, se estima: la unidad
número *k* cuesta `precio × (1 + subida × k / ventas diarias)`, con «subida» ajustable (30 % por
defecto) y las ventas diarias sacadas del historial de la API.

Retorno de recursos: `1 − 1 / (1 + bonus)`, con bonus 18 % base, +15 % en la ciudad con bonus de
fabricación (+40 % en refinado) y +59 % con foco. Tasa del taller: valor del objeto × 0,1125 × tasa por
100 de nutrición / 100. Las recetas salen de `data/recipes.json` (`scripts/build_recipes.py`).

## Favoritos, historial y ganancias

Botón **☆ Favoritos · Historial · Ganancias** en Windows y pestaña **Más** en la web.

- **Favoritos y avisos de precio:** objetos seguidos con un precio objetivo («avísame si baja de» o
  «si sube de»). Se comprueban a mano o cada 10 minutos mientras la app esté abierta.
- **Historial de precios:** gráfica del precio medio diario por ciudad en los últimos 28 días, con
  el último precio, la media de 7 días y las ventas al día.
- **Registro de ganancias:** apuntas tus operaciones y calcula el beneficio con impuestos. Totales de
  hoy, 7 días y total; se exporta a CSV.

La pestaña **Ranking** de las Calculadoras repasa todas las recetas y ordena qué da más beneficio al
fabricar o refinar. En Windows, favoritos y ganancias se guardan en `%APPDATA%\AlbionBM\`.

## Versión web (móvil)

En `web/`, publicada con GitHub Pages. Usa solo la API (no lee el juego) y guarda tus datos en el
propio navegador. Además de oportunidades, plan y calculadoras, tiene:

- **Ranking de fabricación:** repasa todas las recetas con los precios de la API y ordena qué da más
  beneficio al fabricar o refinar.
- **Favoritos y avisos de precio:** objetos seguidos con un precio objetivo; avisa mientras la página
  esté abierta.
- **Historial de precios:** gráfica del precio medio diario por ciudad en los últimos 28 días.
- **Registro de ganancias:** apuntas tus operaciones y lleva la cuenta de lo ganado.

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
| `albionbm/calc.py` | Estrategias, oportunidades, precios sospechosos, perfiles y plan de inversión |
| `albionbm/export.py` | Informe en Markdown para pegárselo a Claude |
| `albionbm/gui.py` | Ventana (Tkinter) |
| `data/items.json` | Equipo, recursos, consumibles, monturas y artefactos (T4–T8, nombres en español) |
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
node --test tests/web_calc.test.js tests/web_calculators.test.js
```

## Créditos

El decodificador Photon está adaptado del cliente de
[Albion Online Data Project](https://github.com/ao-data/albiondata-client) (MIT) y de
[AlbionDataAvalonia](https://github.com/JPCodeCraft/AlbionDataAvalonia).
Ver `THIRD_PARTY_NOTICES.md`. No uses este proyecto con fines comerciales.
