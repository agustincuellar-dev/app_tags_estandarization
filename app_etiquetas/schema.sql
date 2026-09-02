-- ============================================================
-- Sistema de Gestión de Tags (Tag Governance) - Ingenio La Florida
-- Esquema de base de datos SQLite
-- Basado en la lógica de identificación de ANSI/ISA-5.1
-- ============================================================
PRAGMA foreign_keys = ON;

-- Áreas de la planta. Cada área tiene un RANGO NUMÉRICO reservado
-- para sus lazos (ej. Molienda usa 100-199, Evaporación 400-499).
-- Esto evita que dos áreas distintas usen el mismo número de lazo.
CREATE TABLE IF NOT EXISTS areas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo          TEXT NOT NULL UNIQUE,      -- ej. 'MOL', 'CAL', 'EVA'
    nombre          TEXT NOT NULL,             -- ej. 'Molienda'
    rango_inicio    INTEGER NOT NULL,          -- ej. 100
    rango_fin       INTEGER NOT NULL,          -- ej. 199
    descripcion     TEXT,
    activo          INTEGER NOT NULL DEFAULT 1,
    CHECK (rango_fin > rango_inicio)
);

-- Primera letra del tag: variable medida (Tabla 1 de ISA-5.1)
CREATE TABLE IF NOT EXISTS variables (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    letra           TEXT NOT NULL UNIQUE,      -- ej. 'P', 'T', 'L', 'F'
    nombre          TEXT NOT NULL,             -- ej. 'Presión'
    descripcion     TEXT
);

-- Letra(s) sucesivas del tag: función del instrumento
CREATE TABLE IF NOT EXISTS funciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    letra           TEXT NOT NULL UNIQUE,      -- ej. 'T', 'IC', 'SH'
    nombre          TEXT NOT NULL,             -- ej. 'Transmisor'
    descripcion     TEXT
);

-- Catálogo de usuarios que registran tags (campo "Registrado por").
-- Se precarga con el personal habitual y se puede ampliar desde la GUI.
CREATE TABLE IF NOT EXISTS usuarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT NOT NULL UNIQUE,      -- ej. 'ariel', 'ricardo'
    activo          INTEGER NOT NULL DEFAULT 1
);

-- Registro maestro de tags ya asignados/instalados/planificados.
-- Esta es la tabla que se consulta para evitar duplicados.
CREATE TABLE IF NOT EXISTS tags (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_completo        TEXT NOT NULL UNIQUE,      -- ej. 'PT-104'
    area_id             INTEGER NOT NULL REFERENCES areas(id),
    variable_id         INTEGER NOT NULL REFERENCES variables(id),
    funcion_id          INTEGER NOT NULL REFERENCES funciones(id),
    numero_loop         INTEGER NOT NULL,
    descripcion         TEXT,                      -- ej. "Presión salida bomba alimentación caldera 2"
    ubicacion           TEXT,                       -- ej. "Sala de calderas, línea 2"
    fabricante          TEXT,
    modelo              TEXT,
    rango_medicion      TEXT,                       -- ej. "0-10"
    unidad              TEXT,                       -- ej. "bar", "°C", "%"
    comentarios         TEXT,                       -- ej. "Válvula de 12 pulgadas"
    estado              TEXT NOT NULL DEFAULT 'Planificado'
                            CHECK (estado IN ('Planificado','Instalado','Fuera de Servicio','Retirado')),
    creado_por          TEXT,
    fecha_creacion      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    fecha_modificacion  TEXT,
    plc_origen          TEXT,                       -- PLC/controlador de origen si el tag
                                                      -- viene de una migracion masiva (ej.
                                                      -- 'DESTILERIA'); NULL en alta manual
    datatype            TEXT,                       -- datatype real del PLC si se conoce
                                                      -- (ej. 'BOOL','REAL','INT') -- meramente
                                                      -- informativo desde que el Tipo de Señal
                                                      -- es un control manual (tipo_senal)
    alias_for           TEXT,                       -- direccion/alias original del .L5X si
                                                      -- se conoce (ej. 'Local:2:I.Data.5',
                                                      -- 'FIT100_IN') -- meramente informativo
                                                      -- desde que Entrada/Salida es un control
                                                      -- manual (entrada_salida)
    fluido_proceso      TEXT,                       -- que fluido/producto maneja el instrumento
                                                      -- (ej. 'Alcohol 90°', 'Flegmasa', 'Agua
                                                      -- pura') -- PURAMENTE INFORMATIVO, nunca
                                                      -- entra en tag_completo (el Manual de
                                                      -- Estandarizacion prohibe nombres de
                                                      -- material de proceso en el tag)
    tipo_senal          TEXT DEFAULT 'Desconocido', -- control MANUAL en la UI (Paso 3); antes
                                                      -- se inferia del datatype. 'Desconocido'
                                                      -- es el valor honesto de las filas
                                                      -- historicas (no se sabe todavia)
    entrada_salida      TEXT DEFAULT 'N/D'          -- control MANUAL en la UI (Paso 3); antes
                                                      -- se inferia del AliasFor del .L5X
                                                      -- ('N/D' = no se sabe / no aplica)
);

CREATE INDEX IF NOT EXISTS idx_tags_area        ON tags(area_id);
CREATE INDEX IF NOT EXISTS idx_tags_correlativo  ON tags(area_id, variable_id, funcion_id);

-- Bitácora simple de auditoría (quién creó/modificó qué y cuándo)
CREATE TABLE IF NOT EXISTS auditoria (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id          INTEGER REFERENCES tags(id),
    accion          TEXT NOT NULL,             -- 'CREACION', 'MODIFICACION', 'CAMBIO_ESTADO'
    detalle         TEXT,
    usuario         TEXT,
    fecha           TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ============================================================
-- Aprendizaje por Excepcion (motor de auditoria ISA -- auditar_l5x.py)
-- ------------------------------------------------------------
-- Reemplaza el patron de "parche global en Python" por reglas que vive
-- en datos: un tag que el motor no supo clasificar (ej. 'FIT100', el
-- homonimo 'DES') queda archivado en tags_no_clasificados; un usuario lo
-- resuelve una vez con un clic y esa resolucion queda en
-- reglas_aprendidas, disponible para que la PROXIMA corrida del motor
-- lo resuelva sola, sin tocar codigo. Ver docs/Roadmap_Arquitectura_Inteligente.md.
-- ============================================================

-- Reglas de clasificacion aprendidas: mapea un patron de nombre de tag
-- (exacto o por prefijo) a la accion que el motor debe tomar.
CREATE TABLE IF NOT EXISTS reglas_aprendidas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patron          TEXT NOT NULL,             -- ej. 'FIT100', 'FIT', o una
                                                -- expresion regular (ver tipo_match)
    tipo_match      TEXT NOT NULL DEFAULT 'EXACTO'
                        CHECK (tipo_match IN ('EXACTO', 'PREFIJO', 'REGEX')),
                                                -- REGEX: para familias que se parten
                                                -- por SUFIJO y no por prefijo, ej.
                                                -- '^ME\d.*_CORRENTE$' (corriente de
                                                -- motor -> IT) vs '^ME\d.*_Reference$'
                                                -- (consigna al variador -> INTERNA):
                                                -- mismo prefijo 'ME', destinos opuestos.
    plc_nombre      TEXT,                      -- NULL = aplica a TODOS los PLCs;
                                                -- si no es NULL, la regla es scoped
                                                -- (match por prefijo del nombre de
                                                -- archivo, igual criterio que
                                                -- AREA_DEFECTO_POR_PLC en auditar_l5x.py)
    accion          TEXT NOT NULL
                        CHECK (accion IN ('FUNCION_ISA', 'INTERNA', 'EQUIPOS_LOGICA',
                                          'FISICO_ISA', 'RESERVADO')),
    funcion_isa     TEXT,                      -- ej. 'F', 'PT', 'D' -- solo si accion='FUNCION_ISA'
    motivo          TEXT,                      -- por que existe la regla (para el proximo humano)
    activo          INTEGER NOT NULL DEFAULT 1,
    creado_por      TEXT,
    fecha_creacion  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (patron, tipo_match, plc_nombre)
);

CREATE INDEX IF NOT EXISTS idx_reglas_patron ON reglas_aprendidas(patron, activo);

-- Bandeja de pendientes: tags que el motor no supo clasificar en la
-- ultima corrida. En vez de morir en el CSV _sin_clasificar, quedan aca
-- a la espera de que alguien les asigne una regla (o los descarte).
CREATE TABLE IF NOT EXISTS tags_no_clasificados (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    plc_nombre              TEXT NOT NULL,
    tag_original            TEXT NOT NULL,
    datatype                TEXT,
    alias_for               TEXT,
    motivo_no_clasificado   TEXT,              -- nota que ya genera el motor
                                                -- (columna 'validacion' del CSV)
    fecha_deteccion         TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    estado                  TEXT NOT NULL DEFAULT 'Pendiente'
                                CHECK (estado IN ('Pendiente', 'Regla_Creada', 'Descartado')),
    regla_aplicada_id       INTEGER REFERENCES reglas_aprendidas(id),
    resuelto_por            TEXT,
    fecha_resolucion        TEXT,
    UNIQUE (plc_nombre, tag_original)
);

CREATE INDEX IF NOT EXISTS idx_no_clasificados_estado ON tags_no_clasificados(plc_nombre, estado);
