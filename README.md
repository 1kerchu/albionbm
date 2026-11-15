# Albion · Mercado Negro

Aplicación web para **Albion Online** que compara el precio de los objetos en los mercados de las ciudades
con lo que paga el **Mercado Negro** (Caerleon) y los ordena por beneficio, en plata y en porcentaje.

Los precios vienen de la API pública de [Albion Online Data Project](https://www.albion-online-data.com/),
que se alimenta de los jugadores que usan su cliente de datos. Por eso **pueden estar desactualizados**:
la columna «Datos» indica la antigüedad, y conviene comprobar el precio en el juego antes de comprar.

## Cómo usarla

No necesita instalación: abre `index.html` con doble clic en el navegador.

(Opcional) Si prefieres servirla: `npm start` y abre <http://localhost:8080>.

1. Elige el servidor (Europa, América o Asia).
2. Marca categorías, tiers, encantamientos, calidades y las ciudades donde quieres comprar.
3. Pulsa **Buscar oportunidades**. La tabla se rellena mientras llegan los datos.
4. Haz clic en las cabeceras para ordenar (por defecto, por % de beneficio).

## Cómo calcula el beneficio

| Concepto | Fórmula |
|---|---|
| Coste (compra directa) | precio de venta más bajo en la ciudad |
| Coste (orden de compra) | orden de compra más alta en la ciudad × 1,025 (tasa de publicación 2,5 %) |
| Recibes | orden de compra más alta del Mercado Negro × (1 − impuesto) — impuesto 4 % con prémium, 8 % sin |
| Beneficio | Recibes − Coste |
| % | Beneficio / Coste × 100 |

Una orden del Mercado Negro de calidad Q acepta objetos de calidad Q o superior, así que un objeto
«Notable» se compara con la mejor orden de calidad Normal, Buena o Notable.

Se descartan precios más antiguos que el límite de horas elegido.

## Estructura

- `index.html`, `css/style.css`, `js/app.js`: interfaz.
- `js/calc.js`: cálculo de oportunidades (sin DOM, con tests).
- `data/items.js`: objetos que compra el Mercado Negro (armas, armaduras, cascos, botas, secundarias,
  bolsas, capas y equipo de recolección, T4–T8, con nombre en español).
- `scripts/build_items.py`: regenera `data/items.js` cuando sale contenido nuevo:

  ```bash
  curl -o /tmp/items_raw.json https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.json
  curl -o /tmp/items_fmt.json https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.json
  python3 scripts/build_items.py /tmp/items_raw.json /tmp/items_fmt.json
  ```

## Tests

```bash
npm test
```
