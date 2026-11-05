# Botones plasma

Complemento de FreeCAD con botones para el **corte por plasma** (FreeCAD CAM,
LinuxCNC / QtPlasmaC). Los botones que valen para cualquier tecnología de corte
están en [botones-generales](https://github.com/rubenturra/botones-generales).

## Mecanizar plasma

Botón en la barra **Plasma** del banco de trabajo CAM. Usa las piezas
seleccionadas o todo el resultado del anidado (1st Nesting) y, por cada chapa:

1. crea el trabajo CAM con material, herramienta (kerf) y perfil exterior/agujeros;
2. postprocesa (por defecto `linuxcnc`);
3. adapta el programa a **QtPlasmaC**: agujeros primero, sin Z, `M3 $0 S1`/`M5 $0`,
   velocidad del material de QtPlasmaC;
4. calcula entradas y salidas (recta, arco o ninguna; en lado o en esquina;
   sentido horario/antihorario), separadas para exteriores e interiores,
   alejando la perforación de las piezas vecinas;
5. dibuja el G-code y las perforaciones, comprueba el resultado y lo guarda como
   `<nombre>-AAAAMMDD-HHMM_QtPlasmaC.ngc`;
6. opcionalmente guarda el **retal** como DXF para 1st Nesting y abre la
   **simulación** del programa final.

La carpeta y el nombre del programa se recuerdan. Los retales se guardan en la
carpeta de la *Biblioteca de retales* de 1st Nesting (si no hay, en
`Documentos/Retales`).

Antes de cortar: elige el material en QtPlasmaC y haz una pasada en vacío.

### Marcado (líneas de pliegue)

Las **líneas sueltas** de una pieza (aristas que no son de ninguna cara, por
ejemplo las líneas de pliegue de un desplegado de chapa metálica guardadas como
compuesto *sólido + líneas*) se **marcan con plasma antes de cortar**. 1st Nesting
las lleva con la pieza al anidarla, así que caen en su sitio en la chapa.

- El programa carga el material de marcado (`M190 P<n>` + `M66 P3 L3 Q1`), marca
  todas las líneas (rectas con `G1`, arcos con `G2`/`G3`) y vuelve al material de
  corte antes del primer corte.
- Cada recta se acorta un poco por cada extremo para no morder el canto.
- En la vista y en la **simulación** el marcado sale en naranja, antes de los cortes.
- Preferencias (`BaseApp/Preferences/Macros/MecanizarPlasma`):
  `MaterialMarcado` (90 por defecto), `MaterialCorte` (1) y `MarcadoRecorte` (2 mm).
  Pon los números de tu tabla de materiales de QtPlasmaC.

## Instalación

1. *Herramientas → Addon Manager → ⚙ Configuración → Repositorios personalizados*:
   añade `https://github.com/rubenturra/botones-plasma` con la rama `main`.
2. Instala **botones-plasma** y reinicia FreeCAD.

## Windows y Linux

Funciona igual en Windows y en Linux (FreeCAD de paquete, AppImage, snap o
flatpak) y en ordenadores con más o menos núcleos:

- los cálculos en paralelo (perfiles, entradas/salidas, informes PDF) usan un
  FreeCAD sin ventana (`FreeCADCmd`/`freecadcmd`), que se busca solo;
- usan todos los núcleos menos uno; si **LinuxCNC** está en marcha en el mismo
  PC dejan dos núcleos libres y arrancan con la prioridad más baja (`nice 19` en
  Linux), para no molestar nunca al control de la máquina;
- los informes PDF se dibujan sin pantalla (`QT_QPA_PLATFORM=offscreen` en Linux).
