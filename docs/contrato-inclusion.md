# Contrato de inclusión de DARQ

Este documento fija qué contenido institucional entra en DARQ y con qué forma. Lo administra el equipo de I+D (Pablo, Walter, Aníbal) según la gobernanza descrita en `docs/adr/0004-gobernanza-de-agregados.md`.

## El criterio está invertido respecto del contrato de Pegasus, y a propósito

El contrato de inclusión de Pegasus (`contrato-inclusion-artifacts.md`, en el repositorio del motor) retiró de su release público dos piezas de contenido: `skill-versiones-estandar-asi` y `laravel-security`. La razón que da ese documento no es de secreto ni de calidad — es de **alcance**: un producto público de uso general no tiene por qué embarcar de fábrica la política de tecnología interna de una organización particular. Eso es correcto ahí, y seguiría siendo correcto aunque el contenido fuera irreprochable: no es una cuestión de qué tan bueno es el contenido, es una cuestión de para quién es el producto que lo distribuye.

DARQ existe para ser, exactamente, el lugar donde ese mismo contenido sí pertenece. Los dos contratos no se contradicen — son complementarios, y cada uno resuelve la mitad del problema que el otro deja afuera a propósito:

| | Pegasus | DARQ |
|---|---|---|
| Para quién | Cualquier equipo, cualquier organización | La DGISIS y sus GO |
| Qué rechaza | Política interna de una organización particular | Contenido genérico cuya casa natural sigue siendo el motor |
| Qué acepta | Guía genérica, reusable fuera de esta organización | Lo propio de la DGISIS, y lo que el motor dejó afuera por alcance |

Lo que Pegasus retira por ser demasiado específico es, con el mismo criterio y sin ninguna contradicción, lo que DARQ existe para incluir.

## Qué califica como contenido institucional para la DGISIS

DARQ acepta dos cosas distintas, y hay que nombrarlas por separado porque no entran por el mismo motivo. Presentarlas como una sola es lo que volvía este documento contradictorio consigo mismo.

**Lo propio de la DGISIS.** Específico de la organización: fuera de ella no tiene sentido.

- Estándares de tecnología propios (el caso fundacional: el estándar de versiones ASI).
- Skills de operación de infraestructura propia de una GO (el caso en curso: operar OpenShift vía `oc`, aportado por la GO de implementaciones).
- Cualquier contenido futuro con ese perfil: útil puertas adentro, y sin sentido genérico fuera.

**Lo que el motor decidió no embarcar, y que la DGISIS sostiene para sus equipos.** Acá la especificidad no está en el contenido: está en la decisión. Pegasus lo retiró de su release público por alcance —no por calidad ni por secreto— y alguien tiene que seguir manteniéndolo para quienes lo usan. Ese alguien es la DGISIS.

- Seguridad Laravel es exactamente este caso, y conviene decirlo con todas las letras: **es guía genérica**, aplicable a cualquier equipo que use el framework, y lo único propio de la organización que tiene es su `author`. No entra por ser específica. Entra porque el producto público la dejó afuera y acá hay equipos que trabajan con Laravel. Durante un tiempo este documento la presentó como «específica de cómo trabaja la DGISIS», que no era cierto: convertía al caso fundacional en el contraejemplo del criterio que el mismo documento declara dos secciones más abajo.

La prueba para lo que **no** entra es de una sola pregunta: ¿alguien fuera de la DGISIS lo querría, y el producto público está dispuesto a distribuirlo? Si las dos respuestas son sí, su casa es el motor y no DARQ. Un «sí» y un «no» —lo quieren afuera pero el motor no lo embarca— es justamente la segunda categoría de arriba.

## La forma es no negociable: skill seleccionado por relevancia, nunca regla hardcodeada

Un estándar institucional entra a DARQ como un skill que el orquestador elige según el contexto de la tarea — nunca como una regla que el producto aplica de forma incondicional a todo el mundo.

La razón no es de preferencia de diseño, es organizacional: la GO de implementaciones opera OpenShift directamente y no programa. El estándar de versiones ASI no le aplica, y no tiene sentido que le aplique — no hay versión de framework que homologar cuando el trabajo es administrar clústers vía `oc`. Si el estándar ASI estuviera cableado en el producto en lugar de vivir como skill seleccionado por relevancia, cada GO que no encaja en su premisa quedaría forzada a convivir con una regla que no le corresponde, o el producto tendría que empezar a distinguir GOs por código — exactamente el tipo de acoplamiento que la ADR 0002 prohíbe. Un skill que el orquestador selecciona por relevancia resuelve esto sin que el motor necesite saber qué GO es cuál: aplica donde el contexto lo amerita y queda inerte donde no.

## Contenido que no requiere cambio de motor

Un agregado a DARQ es contenido — markdown, frontmatter, referencias — nunca una necesidad de capacidad nueva del motor. Si algo que se quiere agregar solo es posible cambiando cómo Pegasus resuelve, adapta o materializa contenido, no es un agregado de DARQ: es una propuesta de mejora para Pegasus (ver `docs/adr/0001-distribucion-no-fork.md`), y el agregado espera a que esa mejora exista en un release publicado.

## Provenance y owner

Todo contenido que entra a DARQ trae su procedencia — de qué GO o equipo viene, para qué situación institucional se escribió — y un owner nombrado que responde por él en el tiempo: quien lo actualiza si el estándar cambia, quien lo retira si deja de aplicar. Contenido sin owner no se acepta, sin importar su calidad.

## Qué DARQ no embarca

- Nada que sea competencia o superposición con lo que ya presenta la dirección ejecutiva ("ASI Harness") — DARQ es la distribución de la DGISIS, no una alternativa a esa iniciativa (ver `docs/adr/0003-no-se-llama-harness.md`).
- Nada específico de otras áreas fuera de la DGISIS y sus GO — el harness que está construyendo el equipo de Rocío (GO de proyectos) para otras áreas es un esfuerzo separado, con su propio criterio de inclusión.
- Ninguna capacidad de motor nueva ni ningún fork de código de Pegasus — eso es exactamente lo que la ADR 0001 cierra.
- Contenido genérico cuya casa natural sigue siendo el motor: si Pegasus lo embarca, o lo embarcaría, su lugar es Pegasus. Lo que el motor retiró por alcance es otra cosa y sí entra — ver «Qué califica como contenido institucional».
- Contenido sin owner nombrado.

## El residuo de marca conocido, y por qué es deliberado

DARQ no copia el árbol de contenido de Pegasus: lo hereda a través de una transformación de rebranding aplicada sobre el release fijado (ver ADR 0001). Esa transformación no borra cada aparición literal de "pegasus" del contenido heredado — y no debería: en varios lugares esa cadena es un identificador de protocolo estable, compartido por definición entre Pegasus y cualquier distribución construida sobre él (por ejemplo, un esquema de journal o de catálogo versionado como `pegasus-harness/journal/v4` o `pegasus/artifact-catalog/v4`). Reescribir esas cadenas rompería la compatibilidad con el propio motor que DARQ consume, sin ganar nada a cambio: el lector de esos identificadores es código, no una persona formándose una impresión de marca.

Ese puñado de trazas es un residuo conocido y aceptado, no un descuido. La regla para distinguirlo de un descuido real: si la cadena es un identificador de wire compartido por todo el ecosistema de distribuciones, se queda. Si es texto de cara al usuario — un título, una descripción, un mensaje — y dice "Pegasus" donde debería decir "DARQ", es un bug de la transformación de rebranding, no un residuo aceptado, y se corrige donde vive esa transformación.

## Referencias

- `docs/adr/0001-distribucion-no-fork.md` — por qué DARQ no puede requerir cambios de motor para incluir contenido.
- `docs/adr/0002-marca-sin-expansion.md` — por qué la forma del contenido (skill, no regla) es la misma disciplina que gobierna las capacidades.
- `docs/adr/0004-gobernanza-de-agregados.md` — quién aplica este contrato y cómo.
