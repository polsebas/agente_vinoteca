"""
Carga 15 vinos de prueba con datos reales de bodegas argentinas.
También indexa fragmentos de conocimiento por capa para el RAG del Sumiller.
Ejecutar: python scripts/seed_catalog.py
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

VINOS: list[dict] = [
    {
        "nombre": "Achaval Ferrer Malbec",
        "bodega": "Achaval Ferrer",
        "varietal": "Malbec",
        "cosecha": 2021,
        "precio": 4500.00,
        "descripcion": "Malbec de alta gama de Mendoza, terroir excepcional.",
        "region": "Mendoza",
        "sub_region": "Luján de Cuyo",
        "alcohol": 14.5,
        "maridajes": ["asado", "cordero", "quesos duros"],
        "stock": 24,
        "conocimiento": {
            1: "Malbec 100%, cosecha 2021. Alcohol 14,5%. Precio $4.500. Color rojo rubí profundo.",
            2: "Proviene de viñedos en Luján de Cuyo a 900 metros sobre el nivel del mar. Suelos pedregosos con alta carga mineral que le dan estructura y frescura al vino.",
            3: "Bodega fundada en 1998 por Roberto Cipresso y socios. Desde el inicio apostaron por la expresión del terroir sin maquillaje. El enólogo Santiago Achaval toma decisiones mínimamente intervencionistas.",
            4: "Los Malbec de Luján de Cuyo están siendo redescubiertos por la crítica internacional como la expresión más elegante del varietal. Menos potencia, más fineza que los de altitud.",
            5: "Lo elegimos porque su relación calidad-precio es imbatible. Es el vino que recomendamos cuando alguien quiere quedar bien sin gastar una fortuna. El 2021 fue una cosecha espectacular en Mendoza.",
        },
    },
    {
        "nombre": "Clos de los Siete",
        "bodega": "Clos de los Siete",
        "varietal": "Blend (Malbec, Merlot, Cabernet Sauvignon)",
        "cosecha": 2020,
        "precio": 6800.00,
        "descripcion": "Blend icónico del Valle de Uco, proyecto de Michel Rolland.",
        "region": "Mendoza",
        "sub_region": "Valle de Uco",
        "alcohol": 14.8,
        "maridajes": ["carnes rojas", "caza", "pasta con ragu"],
        "stock": 18,
        "conocimiento": {
            1: "Blend de Malbec, Merlot y Cabernet Sauvignon, cosecha 2020. Alcohol 14,8%.",
            2: "Valle de Uco, a 1.100 metros de altitud. Amplitud térmica de 20°C entre día y noche que preserva la acidez natural de las uvas.",
            3: "Proyecto creado por el enólogo francés Michel Rolland junto con seis bodegas del Valle de Uco. Vinificación separada por parcela y varietal, blend final en noviembre.",
            4: "Los vinos de Valle de Uco lideran las listas de los mejores vinos argentinos. La altitud es la nueva frontera de calidad.",
            5: "Ideal para regalo de impacto. Cuando el cliente quiere dar algo memorable, este vino siempre genera una respuesta emotiva. El packaging también ayuda.",
        },
    },
    {
        "nombre": "Zuccardi Valle de Uco",
        "bodega": "Zuccardi",
        "varietal": "Malbec",
        "cosecha": 2022,
        "precio": 3200.00,
        "descripcion": "Malbec fresco y frutal del Valle de Uco.",
        "region": "Mendoza",
        "sub_region": "Valle de Uco",
        "alcohol": 13.8,
        "maridajes": ["pollo a la parrilla", "pasta con tomate", "mozzarella"],
        "stock": 36,
        "conocimiento": {
            1: "Malbec 100%, Valle de Uco, cosecha 2022. Alcohol 13,8%. Vino de entrada de la línea Valle.",
            2: "Fruta de viñedos en Paraje Altamira y San Pablo. El suelo calizo de Altamira le da una tipicidad mineral única.",
            3: "Familia Zuccardi lleva tres generaciones en Mendoza. José Alberto Zuccardi es referente mundial. Su hijo Sebastián es hoy el enólogo.",
            4: "Zuccardi es la bodega argentina del momento. Fue elegida como Mejor Bodega del Mundo por la World's Best Vineyards.",
            5: "El vino perfecto para el que está empezando a explorar el Malbec. Fresco, frutal, sin taninos agresivos. No falla nunca.",
        },
    },
    {
        "nombre": "Catena Zapata Adrianna Vineyard",
        "bodega": "Catena Zapata",
        "varietal": "Malbec",
        "cosecha": 2020,
        "precio": 28000.00,
        "descripcion": "El Malbec más valorado de Argentina. Viñedo Adrianna a 1.500m.",
        "region": "Mendoza",
        "sub_region": "Gualtallary",
        "alcohol": 14.2,
        "maridajes": ["cordero patagónico", "quesos añejos", "solo como celebración"],
        "stock": 6,
        "conocimiento": {
            1: "Malbec de viñedo único Adrianna, 2020. Alcohol 14,2%. El Adrianna Vineyard es considerado por Robert Parker como uno de los mejores viñedos del mundo.",
            2: "Gualtallary, a 1.500 metros de altitud. Es el viñedo a mayor altitud de la familia Catena. Las temperaturas nocturnas bajan hasta 7°C en verano, preservando acidez perfecta.",
            3: "Laura Catena, doctora en medicina de Harvard, es la cara pública de la bodega. Ella misma recorre el viñedo en cada cosecha. El abuelo Nicola llegó de Italia en 1898.",
            4: "El Adrianna Vineyard está en el top 10 de viñedos del mundo según Robert Parker y Wine Spectator. Los vinos de Gualtallary son el techo de calidad del Malbec argentino.",
            5: "Solo para el cliente que realmente entiende de vinos y tiene presupuesto alto. No lo recomendamos sin antes preguntar la ocasión. Es un vino que se abre en momentos muy especiales.",
        },
    },
    {
        "nombre": "Cheval des Andes",
        "bodega": "Cheval des Andes",
        "varietal": "Blend (Malbec, Cabernet Sauvignon)",
        "cosecha": 2019,
        "precio": 22000.00,
        "descripcion": "Joint venture con Château Cheval Blanc. Elegancia bordelesa en Mendoza.",
        "region": "Mendoza",
        "sub_region": "Luján de Cuyo",
        "alcohol": 14.0,
        "maridajes": ["filete", "confit de pato", "cena de gala"],
        "stock": 8,
        "conocimiento": {
            1: "Blend de Malbec y Cabernet Sauvignon, cosecha 2019. Alcohol 14,0%.",
            2: "Luján de Cuyo, viñedos históricos de Terrazas de los Andes. Suelos aluviales con piedras rodadas que elevan la temperatura del suelo y aceleran la maduración.",
            3: "Joint venture entre el mítico Château Cheval Blanc de Saint-Émilion y Terrazas de los Andes. Única bodega argentina co-creada por un Grand Cru Classé francés.",
            4: "Combina la filosofía bordelesa de blends complejos con la intensidad del terroir mendocino. Único en su tipo.",
            5: "Para el que busca impresionar a alguien que conoce vinos de Burdeos. La historia del proyecto genera conversación en la mesa.",
        },
    },
    {
        "nombre": "Luigi Bosca Gala 2",
        "bodega": "Luigi Bosca",
        "varietal": "Blend (Viognier, Chardonnay)",
        "cosecha": 2022,
        "precio": 5400.00,
        "descripcion": "Blend blanco de alta gama. Fresco, aromático y complejo.",
        "region": "Mendoza",
        "sub_region": "Maipú",
        "alcohol": 13.5,
        "maridajes": ["salmón", "langostinos", "risotto de mariscos"],
        "stock": 12,
        "conocimiento": {
            1: "Blend de Viognier y Chardonnay, cosecha 2022. Alcohol 13,5%. Fermentado en barrica nueva.",
            2: "Maipú, zona histórica de Mendoza. Viñedos de más de 80 años, lo que le da concentración y complejidad natural.",
            3: "Luigi Bosca es una de las bodegas más antiguas de Argentina, fundada en 1901. Cuarta generación de la familia Arizu.",
            4: "Los blancos de alta gama de Argentina están ganando reconocimiento internacional. El Viognier mendocino es aromáticamente superior a los europeos.",
            5: "Para el que pide un blanco de categoría y quiere algo diferente al Chardonnay clásico. El Viognier sorprende siempre.",
        },
    },
    {
        "nombre": "Clos de Chacras Torrontés",
        "bodega": "Clos de Chacras",
        "varietal": "Torrontés",
        "cosecha": 2023,
        "precio": 1800.00,
        "descripcion": "Torrontés de Cafayate, fresco y perfumado. La variedad emblema de Salta.",
        "region": "Salta",
        "sub_region": "Cafayate",
        "alcohol": 13.0,
        "maridajes": ["empanadas", "ceviche", "comida picante"],
        "stock": 48,
        "conocimiento": {
            1: "Torrontés 100%, Cafayate, cosecha 2023. Alcohol 13,0%. Varietal emblema de Argentina.",
            2: "Cafayate, a 1.700 metros sobre el nivel del mar en el NOA. Clima árido, muy pocas lluvias. El calor del día y el frío de la noche producen Torrontés perfumados e intensos.",
            3: "El Torrontés de Cafayate es la única variedad blanca con denominación de origen argentina reconocida internacionalmente.",
            4: "El Torrontés está siendo descubierto por sommeliers internacionales como la alternativa a Gewürztraminer. Tendencia creciente en cartas de vino de restaurantes de autor.",
            5: "Para el aperitivo perfecto o el que no quiere tinto en verano. Muy accesible en precio. Siempre sorprende positivamente a quien no lo conoce.",
        },
    },
    {
        "nombre": "Achaval Ferrer Finca Altamira",
        "bodega": "Achaval Ferrer",
        "varietal": "Malbec",
        "cosecha": 2020,
        "precio": 9800.00,
        "descripcion": "Vino de finca única de Altamira, Valle de Uco.",
        "region": "Mendoza",
        "sub_region": "Valle de Uco",
        "alcohol": 14.3,
        "maridajes": ["cordero", "venado", "ojo de bife"],
        "stock": 10,
        "conocimiento": {
            1: "Malbec de viñedo único Finca Altamira, cosecha 2020. Alcohol 14,3%.",
            2: "Paraje Altamira tiene suelo calizo único en Mendoza. El carbonato de calcio le da mineralidad y tensión excepcional al vino. Viñedos a 1.050 metros.",
            3: "Santiago Achaval decidió en 2005 hacer single vineyards para mostrar la expresión individual de cada parcela. Fue pionero en Argentina.",
            4: "Los single vineyards de Valle de Uco son el segmento de mayor crecimiento en exportaciones argentinas de alta gama.",
            5: "Lo recomendamos para el coleccionista que ya conoce el Achaval Ferrer estándar y quiere ir un paso más. La mineralidad de Altamira es única en Argentina.",
        },
    },
    {
        "nombre": "Mendel Unus",
        "bodega": "Mendel Wines",
        "varietal": "Blend (Malbec, Cabernet Sauvignon)",
        "cosecha": 2019,
        "precio": 8500.00,
        "descripcion": "Blend premium de Roberto de la Mota. Elegancia y longevidad.",
        "region": "Mendoza",
        "sub_region": "Luján de Cuyo",
        "alcohol": 14.2,
        "maridajes": ["asado de tira", "quesos duros", "charcutería"],
        "stock": 14,
        "conocimiento": {
            1: "Blend de Malbec y Cabernet Sauvignon, cosecha 2019. Alcohol 14,2%.",
            2: "Viñedos centenarios en Luján de Cuyo. Las vides de más de 80 años producen naturalmente menos cantidad pero más concentración.",
            3: "Roberto de la Mota es considerado uno de los mejores enólogos de América Latina. Trabajó en Cheval des Andes antes de fundar Mendel.",
            4: "Los vinos de viñas viejas están en tendencia. Menor intervención, mayor expresión del terroir.",
            5: "Para el amante del vino que aprecia la historia detrás de la botella. Contar quién es De la Mota siempre genera interés.",
        },
    },
    {
        "nombre": "Tapiz Black Tears Malbec",
        "bodega": "Tapiz",
        "varietal": "Malbec",
        "cosecha": 2022,
        "precio": 2100.00,
        "descripcion": "Malbec de Valle de Uco. Accesible, frutal y redondo.",
        "region": "Mendoza",
        "sub_region": "Valle de Uco",
        "alcohol": 13.5,
        "maridajes": ["pizza", "hamburgesa", "asado del domingo"],
        "stock": 60,
        "conocimiento": {
            1: "Malbec 100%, Valle de Uco, cosecha 2022. Alcohol 13,5%. Línea de entrada de Tapiz.",
            2: "Valle de Uco en su versión más accesible. Sin crianza en madera, preserva la fruta fresca del Malbec joven.",
            3: "Bodega joven, fundada en 2000. Apuesta por vinos frescos y modernos para nuevo consumidor.",
            4: "El segmento de Malbec accesible está creciendo. El consumidor joven busca buena calidad sin pagar de más.",
            5: "El Malbec perfecto para el domingo en casa. Nunca falla, siempre gusta. Relación precio-placer imbatible.",
        },
    },
    {
        "nombre": "Rutini Encuentro Blend",
        "bodega": "Rutini Wines",
        "varietal": "Blend (Cabernet Sauvignon, Merlot, Malbec)",
        "cosecha": 2021,
        "precio": 7200.00,
        "descripcion": "Blend de autor de Tupungato. Complejo y estructurado.",
        "region": "Mendoza",
        "sub_region": "Tupungato",
        "alcohol": 14.5,
        "maridajes": ["cordero asado", "caza mayor", "quesos estacionados"],
        "stock": 16,
        "conocimiento": {
            1: "Blend de Cabernet Sauvignon, Merlot y Malbec, cosecha 2021. 24 meses en barrica francesa.",
            2: "Tupungato, extremo norte del Valle de Uco. Suelos volcánicos que aportan notas minerales y especiadas únicas.",
            3: "Bodega Rutini lleva 100 años en Mendoza. La línea Encuentro representa su visión más ambiciosa.",
            4: "Tupungato es la nueva frontera de los vinos de alta gama. Menos conocida que Altamira pero igualmente excepcional.",
            5: "Para el conocedor que quiere explorar fuera de los varietales habituales. El blend sorprende por su complejidad.",
        },
    },
    {
        "nombre": "La Posta Parcela Los Barriales",
        "bodega": "La Posta",
        "varietal": "Malbec",
        "cosecha": 2022,
        "precio": 3800.00,
        "descripcion": "Malbec de parcela única en Maipú. Concentrado y accesible.",
        "region": "Mendoza",
        "sub_region": "Maipú",
        "alcohol": 14.0,
        "maridajes": ["asado", "milanesas", "empanadas de carne"],
        "stock": 30,
        "conocimiento": {
            1: "Malbec de parcela Los Barriales, Maipú. Cosecha 2022. Alcohol 14,0%.",
            2: "Maipú, zona histórica donde nació el Malbec argentino moderno. Suelos aluvionales con piedras que drenen perfectamente.",
            3: "La Posta es el proyecto de Laura Catena para vinos accesibles con el mismo rigor de Catena Zapata. Cada vino lleva el nombre del viticultor que trabajó esa parcela.",
            4: "El modelo de transparencia en producción, nombrar al viticultor, está ganando adeptos. Crea conexión humana con el vino.",
            5: "Para el cliente que quiere calidad Catena sin pagar precio Catena Zapata. Ideal para regalar con presupuesto medio.",
        },
    },
    {
        "nombre": "Nieto Senetiner Cadus Signature",
        "bodega": "Nieto Senetiner",
        "varietal": "Malbec",
        "cosecha": 2020,
        "precio": 5900.00,
        "descripcion": "Malbec premium de Vistalba. Potente y especiado.",
        "region": "Mendoza",
        "sub_region": "Vistalba",
        "alcohol": 14.8,
        "maridajes": ["carnes rojas a la parrilla", "estofados", "pastas con carne"],
        "stock": 20,
        "conocimiento": {
            1: "Malbec de Vistalba, cosecha 2020. Alcohol 14,8%. 18 meses en barrica de roble americano y francés.",
            2: "Vistalba, microzona de Luján de Cuyo con suelos de gran profundidad. Temperaturas extremas que generan vinos potentes y especiados.",
            3: "Nieto Senetiner es una de las bodegas más grandes de Argentina con historia desde 1888. Cadus es su línea premium.",
            4: "El estilo potente de Vistalba tiene fanáticos en EE.UU. y Brasil. Buena performance en mercados de exportación.",
            5: "Para el amante de los tintos potentes. Si el cliente menciona Parker o Decanter, este es su vino.",
        },
    },
    {
        "nombre": "Clos de Chacras Reserva Pinot Noir",
        "bodega": "Clos de Chacras",
        "varietal": "Pinot Noir",
        "cosecha": 2021,
        "precio": 4200.00,
        "descripcion": "Pinot Noir patagónico de Chacras de Coria. Elegante y ligero.",
        "region": "Patagonia",
        "sub_region": "Neuquén",
        "alcohol": 13.2,
        "maridajes": ["salmón", "pato", "hongos silvestres"],
        "stock": 22,
        "conocimiento": {
            1: "Pinot Noir de Neuquén, cosecha 2021. Alcohol 13,2%. Crianza 12 meses en barrica usada.",
            2: "Neuquén, extremo sur vitícola de Argentina. Clima más frío que Mendoza, ideal para variedades de maduración temprana como Pinot Noir.",
            3: "Los vinos patagónicos están emergiendo como alternativa seria al Pinot Noir de Borgoña. Menos estructura, más fruta.",
            4: "El Pinot Noir patagónico está capturando la atención de sommeliers europeos. Precio accesible comparado con Borgoña.",
            5: "Para el cliente que pide algo diferente al Malbec. El Pinot Noir de Patagonia siempre genera curiosidad y conversación.",
        },
    },
    {
        "nombre": "Familia Zuccardi Concreto",
        "bodega": "Zuccardi",
        "varietal": "Malbec",
        "cosecha": 2021,
        "precio": 12500.00,
        "descripcion": "Fermentado y criado en huevo de concreto. Vino natural de autor.",
        "region": "Mendoza",
        "sub_region": "Valle de Uco",
        "alcohol": 13.5,
        "maridajes": ["quesos de pasta blanda", "embutidos", "solo como meditación"],
        "stock": 8,
        "conocimiento": {
            1: "Malbec de Valle de Uco, cosecha 2021. Fermentación y crianza en huevo de concreto, sin madera. Alcohol 13,5%.",
            2: "El huevo de concreto permite microoxigenación natural sin aportar sabores de madera. El vino desarrolla una textura única y cremosa.",
            3: "Sebastián Zuccardi experimentó con el concreto inspirado en bodegas de Borgoña. En Argentina fue pionero en este formato.",
            4: "El movimiento de vinos sin madera y con mínima intervención es la tendencia más fuerte en el segmento premium mundial.",
            5: "Para el coleccionista o el conocedor que está al día con tendencias. Contar la historia del huevo de concreto genera fascinación.",
        },
    },
]


async def seed(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        for vino in VINOS:
            conocimiento = vino.pop("conocimiento")
            stock_qty = vino.pop("stock")
            maridajes = vino.get("maridajes", [])

            vino_id = await conn.fetchval(
                """
                INSERT INTO vinos (nombre, bodega, varietal, cosecha, precio,
                    descripcion, region, sub_region, alcohol, maridajes)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                vino["nombre"],
                vino["bodega"],
                vino["varietal"],
                vino.get("cosecha"),
                vino["precio"],
                vino.get("descripcion"),
                vino.get("region"),
                vino.get("sub_region"),
                vino.get("alcohol"),
                maridajes,
            )

            if vino_id is None:
                existing = await conn.fetchrow(
                    "SELECT id FROM vinos WHERE nombre = $1 AND bodega = $2",
                    vino["nombre"],
                    vino["bodega"],
                )
                vino_id = existing["id"] if existing else None

            if vino_id:
                await conn.execute(
                    """
                    INSERT INTO stock (vino_id, cantidad)
                    VALUES ($1, $2)
                    ON CONFLICT (vino_id, ubicacion) DO UPDATE SET cantidad = EXCLUDED.cantidad
                    """,
                    vino_id,
                    stock_qty,
                )

                for capa, contenido in conocimiento.items():
                    await conn.execute(
                        """
                        INSERT INTO wine_knowledge (vino_id, capa, contenido, fuente)
                        VALUES ($1, $2, $3, 'seed')
                        ON CONFLICT DO NOTHING
                        """,
                        vino_id,
                        capa,
                        contenido,
                    )

        count = await conn.fetchval("SELECT COUNT(*) FROM vinos")
        print(f"Seed completado: {count} vinos en catálogo.")
    finally:
        await conn.close()


if __name__ == "__main__":
    url = os.environ["DATABASE_URL"]
    asyncio.run(seed(url))
