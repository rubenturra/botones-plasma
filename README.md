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

## Instalación

1. *Herramientas → Addon Manager → ⚙ Configuración → Repositorios personalizados*:
   añade `https://github.com/rubenturra/botones-plasma` con la rama `main`.
2. Instala **botones-plasma** y reinicia FreeCAD.
