# DARQ

DARQ es la distribución institucional de la DGISIS: el mismo motor Pegasus, con
los estándares y skills que los propios equipos de la DGISIS necesitan —
empezando por el estándar de versiones ASI y la skill de seguridad Laravel, y
sumando a futuro contenido aportado por las GO, como una skill para operar
OpenShift vía `oc`. El alcance es explícito: DARQ es para la DGISIS y sus GO,
no para el organismo entero ni un reemplazo de otras iniciativas.

DARQ no contiene una sola línea de código de motor. En tiempo de build descarga
un release publicado y fijado de `pegasus-harness`, verifica su integridad,
le aplica un rebranding declarativo, y le superpone el contenido propio en
`content/`. Ver `docs/adr/0001-distribucion-no-fork.md` para el porqué.

## Instalar

```bash
curl -fsSL https://github.com/balerdis/darq/releases/latest/download/install.sh | bash
```

Esto descarga, verifica e instala DARQ y sus dependencias (nvm, Node LTS y
OpenCode) en una cuenta limpia. `install.sh` acepta además `--verify` (informa
el estado sin cambiar nada), `--yes` (salta la confirmación), `--no-run`
(instala lo que falte pero no lanza nada al final) y `--bin-dir` (para instalar
el binario en un directorio distinto de `~/.local/bin`); correlo con `--help`
para ver la lista completa.

Si preferís no ejecutar un script bajado por `curl` directamente, el camino
manual, hoy:

```bash
# 1. Descargar el binario y su checksum del release que quieras instalar
curl -LO https://github.com/balerdis/darq/releases/download/<tag>/darq
curl -LO https://github.com/balerdis/darq/releases/download/<tag>/darq.sha256

# 2. Verificar el checksum antes de ejecutar nada
sha256sum -c darq.sha256

# 3. Darle permiso de ejecución y ponerlo en el PATH
chmod +x darq
mkdir -p ~/.local/bin && mv darq ~/.local/bin/darq

# 4. Instalar el contenido de DARQ para tu CLI
darq install --cli opencode
```

Reemplazá `<tag>` por el tag del release que vayas a instalar (por ejemplo
`v1.1.0`). Si el checksum no coincide, no lo ejecutes — pedí el release de
nuevo o avisá al equipo de I+D.

## Build desde código fuente

Punto de entrada único:

```bash
tools/check.sh                # guardia anti-fork + build + verificación, en una sola corrida
tools/check.sh --offline      # reusa lo que ya esté en la caché; los checksums se verifican igual
tools/check.sh --no-build     # salta el build, verifica lo que ya esté en dist/darq
```

Lo que hace cada paso, en el orden en que corre:

1. **`tools/check_no_engine_code.py`** — el guardia anti-fork. Confirma que
   ningún archivo del árbol de DARQ es código o contenido del motor: ni un
   directorio con nombre de capa hexagonal (`core`, `ports`, `adapters`,
   `infra`, `tui`), ni un archivo con nombre de contenido conocido del motor,
   ni un `.py` que importe el paquete `pegasus`. Toma el alcance de archivos
   de `git` (`ls-files --cached --others --exclude-standard`), no de una
   lista fija, así que también atrapa algo agregado pero todavía no
   commiteado.
2. **`tools/build_darq.py`** — descarga (o reusa, en `--offline`) el binario
   `pegasus`, `build_zipapp.py`, `build_installer.py` y la plantilla
   `install.sh` publicados en el tag fijado por `engine.pin`, verifica los
   cuatro contra el sha256 pinneado ahí (un mismatch es siempre un error
   fatal, nunca un warning), extrae el paquete, le aplica el rebranding
   declarativo de `rebrand.json` vía `rebrand/transform.py`, superpone
   `content/` encima del árbol ya rebrandeado, arma `dist/darq` con el
   `build_zipapp.py` recién descargado — nunca con una copia local — y genera
   `dist/install.sh` con el `build_installer.py` del motor, a partir del
   `identity.json` propio de DARQ.
3. **`tools/verify_darq.py`** — corre el binario ya construido de verdad,
   dentro de un `$HOME` descartable que el propio script crea y borra: chequea
   `darq --version`, `darq doctor --json`, un `darq install --cli opencode`
   real, la ubicación del data dir, escanea el contenido de los archivos
   instalados bajo `~/.config/opencode` en busca de fugas de marca fuera de
   los tokens de wire protegidos — el alcance exacto de ese escaneo, y lo que
   queda afuera, está en «Deudas» — y además verifica `dist/install.sh`: que
   no mencione al motor en ningún lado, que su
   encabezado de identidad sea el de DARQ, y que `install.sh --help` ande.

### El pin

`engine.pin` fija dos cosas, no una: el tag de `pegasus-harness` que este
build consume, y el sha256 publicado de cada asset de ese tag. El tag dice qué
versión; el hash prueba que lo que se descargó es, byte a byte, lo que ese tag
publicó. Actualizarlo es deliberadamente un diff de un solo archivo — tag y
hashes, nada más en el mismo commit — para que revisarlo no exija leer un
diff de motor, solo confirmar que el hash corresponde al release que dice ser.

## Cómo proponer contenido

La aceptación de agregados a DARQ está centralizada en el equipo de I+D
(Pablo, Walter, Aníbal), según `docs/adr/0004-gobernanza-de-agregados.md`.
El criterio material de qué entra y en qué forma — siempre un skill que el
orquestador elige por relevancia, nunca una regla cableada — está en
`docs/contrato-inclusion.md`. Si estás pensando en aportar algo, empezá por
ese documento.

## Deudas

Trabajo conocido que todavía está por decidirse o por hacerse. Cada fila declara
qué la destraba, para que acarrearla sea una decisión y no un olvido, y qué
puede hacer una persona mientras siga abierta. Acá no va lo que funciona así a
propósito: eso vive en «Limitaciones aceptadas», abajo. Las dos tablas viven en
este mismo archivo, y no en un registro aparte, por una razón concreta: este
README no tiene un solo link de Markdown y este repositorio no tiene validador
de links, así que un puntero a otro documento no lo verificaría nadie.

| Deuda | Qué la destraba | Qué hacer mientras tanto |
|-------|-----------------|--------------------------|
| `balerdis/darq` es un repositorio público —verificado con `gh repo view`— y `content/skills/estandar-versiones-asi/` se describe a sí mismo como política de tecnología interna de la organización, con una matriz de versiones homologadas citando documento y página de fuentes controladas. Su propio `references/provenance.md` sostiene que el asunto es de alcance y no de confidencialidad: los documentos fuente no se redistribuyen, sólo la matriz derivada y sus citas, y ese alcance es exactamente por qué el skill vive en DARQ y no en el motor | Una decisión de gobernanza de quien es dueño del repositorio, no un defecto técnico: si el argumento de alcance alcanza para publicar la matriz derivada, no hay nada que hacer; si no alcanza, lo que cambia es la visibilidad del repositorio o la forma en que se distribuye ese skill. **El 12 de septiembre de 2026 se decidió no atacarla por ahora.** Queda anotada como postergación con el costo a la vista, no como pendiente esperando turno | Nada en el árbol. El motor ya tomó la decisión inversa para su propio release público, y la registra en su propio contrato de inclusión |

## Limitaciones aceptadas

Acá no hay nada pendiente, y esa es la razón de separarla de la tabla de arriba.
Una deuda declara qué la destraba porque se espera que alguna vez se destrabe;
una limitación describe cómo funciona el producto a propósito, con el motivo por
el que se eligió así. Mezclarlas promete en silencio un arreglo para lo que no
va a arreglarse. Una fila se muda de acá para arriba sólo si la decisión se
reabre.

| Limitación | Por qué es así | Qué hacer al respecto |
|------------|----------------|-----------------------|
| Los tests de `tools/check.sh` prueban la **secuenciación** de sus pasos, no que la cadena real de build y verificación funcione. Corren contra un árbol de scratch con herramientas de juguete, habilitado por `DARQ_CHECK_ROOT` | Un test que necesita un `dist/darq` construido y una caché poblada no prueba nada en la máquina donde más importaría, una recién clonada: se saltea, y un «OK (skipped=1)» se lee como cobertura. Entre un test que se saltea y uno que prueba menos pero siempre, el segundo dice la verdad. La cadena real sigue verificándose con una corrida a mano de `tools/check.sh`, que es lo que el procedimiento de release ya exige | Correr `tools/check.sh` de verdad antes de publicar. Y si alguna vez ves el aviso de `DARQ_CHECK_ROOT` en una corrida que creías real, no es decorativo: se está revisando otro árbol. Un detalle conocido — si la raíz apuntada no existe, el `cd` falla antes de que el aviso se imprima, así que ahí sale el error crudo de bash y no el cartel |
| El escáner de fugas de marca corre una sola vez, sobre una sola instalación de un solo CLI. Lo que instalaría un segundo adaptador queda entero fuera del corpus | No es una decisión de alcance sino la ausencia de un sujeto: el motor tiene un solo adaptador, `opencode`, así que no hay una segunda instalación contra la cual correr. Los otros tres huecos que esta fila supo tener —el data dir, los nombres de archivo y los archivos que no decodifican— se cerraron; éste no se cierra, se nombra | Nada hoy. El día que el motor gane un segundo adaptador, este hueco deja de ser teórico y hay que ensanchar la corrida antes de confiar en el resultado |
| Un solo producto por usuario del sistema operativo: DARQ y Pegasus no conviven en la misma cuenta de SO | El motor no hizo seguro compartir `~/.config/opencode` entre dos productos en la misma cuenta: la segunda instalación sobrescribe lo que la primera dejó en esa configuración compartida. El motor lo documenta como comportamiento conocido, no como algo a resolver | Un usuario del sistema operativo por producto. Si hacen falta los dos, hacen falta dos cuentas |
| El plugin de Zellij escribe en `~/.config/pegasus-zellij-state/` y `~/.cache/pegasus-zellij-state/`, con el nombre de marca del motor, aunque el archivo del plugin sí se derive: la instalación deja un `darq-zellij-state.ts` apuntando a un directorio `pegasus-zellij-state` | Es una decisión deliberada del motor, y su propio asset la explica en un comentario: esos directorios viven fuera del directorio de configuración del CLI, ningún journal los reclama y ningún retiro ni migración los alcanzaría con otro nombre, así que derivarlos huerfanaría en silencio el estado que la persona ya tiene en disco — su script de reporte, su log de debug | Nada. Está registrado en `accepted_residue` y `tools/verify_darq.py` lo reporta como NOTE en cada corrida; si dejara de ocurrir, la corrida falla pidiendo que se saque la entrada |
| Las variables de entorno `PEGASUS_*` y los ids de esquema versionados (`pegasus-harness/journal/v4`, `pegasus/cli-report/v1`, `pegasus/artifact-catalog/v4` y similares) se quedan tal cual dentro de los artefactos instalados | Son identificadores de wire estables, compartidos por definición por cualquier distribución construida sobre el mismo motor. Reescribirlos rompería la compatibilidad con el motor que DARQ consume sin ganar nada: quien los lee es código, no una persona formándose una impresión de marca | Nada. Están en `protected_tokens`, que el escáner de fugas enmascara antes de cualquier sustitución y trata como silenciosos por diseño |
| El paquete Python que viaja adentro de `dist/darq` se sigue llamando `pegasus`: el zipapp contiene `pegasus/core/…`, `pegasus/adapters/…`, y ningún `.py` se rebrandea | La sustitución se aplica sólo a `.md` y `.txt`, a propósito: reescribir código fuente sería empezar a mantener un fork, que es exactamente lo que cierra la ADR 0001. Nada de ese namespace es superficie de usuario — los nombres de artefacto en disco, el ejecutable y el data dir se derivan de `identity.json` desde el motor v5.28.0 | Nada. `tools/verify_darq.py` verifica la superficie instalada y la salida de los comandos, que es donde la marca importa |
| Durante `darq doctor`, el motor se presenta ante cada servidor MCP de terceros como `pegasus-doctor`: es el `clientInfo.name` fijo del handshake `initialize` (`CLIENT_NAME` en `core/mcp_handshake.py`, una constante de módulo que no deriva de `identity.json`) | Es un identificador de cliente del ecosistema, de la misma familia que los ids de esquema, y está registrado como tal en `protected_tokens`. Conviene saberlo igual, porque es la única cadena de marca del motor que sale de la máquina de la persona: todo el resto del residuo conocido se queda en disco | Nada en DARQ; derivarlo sería un cambio upstream. Si un servidor MCP de terceros registra qué cliente lo consultó, va a ver `pegasus-doctor`, no `darq` |
| No hay CI en este ecosistema: `.github/` no existe, ni acá ni en el motor | Es una decisión deliberada, registrada en `docs/adr/0001-distribucion-no-fork.md`. El guardia anti-fork corre localmente, a mano o desde `tools/check.sh`, y toma su alcance de lo que reporta `git` en vez de una lista fija, así que atrapa también lo agregado y todavía no commiteado | Correr `tools/check.sh` antes de proponer un cambio o publicar un release. Nada lo va a correr por vos |

## Más contexto

Las decisiones de diseño están documentadas como ADR en `docs/adr/`:
por qué DARQ es una distribución y no un fork (0001), por qué es marca y
contenido y no un segundo producto (0002), por qué no se llama "harness"
(0003), y cómo se gobierna la aceptación de contenido nuevo (0004).
