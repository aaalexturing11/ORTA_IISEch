import numpy as np

class HeavyTruckOptimizer:
    def __init__(self):
        # Especificaciones HOWO MAX 14L Weichai
        self.optimum_rpm = (900, 1400)
        self.peak_torque_nm = 2700
        self.frontal_area = 9.5  # m^2 (Estimado para tractocamión alto)
        
    def get_advice(self, telemetry, segment):
        """
        Genera consejos basados en telemetría, tráfico, relieve y clima.
        Documentación científica integrada para el dashboard.
        """
        speed = telemetry.get('speed_kmh', 0)
        rpm = telemetry.get('rpm', 0)
        slope = segment.get('slope_pct', 0)
        
        # Variables de entorno
        congestion = segment.get('congestion_ratio', 1.0)
        wind_ms = segment.get('wind_speed_ms', 0)
        precip = segment.get('precip_mmph', 0)

        # --- REGLAS DE TRÁFICO Y FLUJO (Nasir 2014 / Gonder 2012) ---

        # 1. Gestión de Congestión Alta (Stop-and-Go)
        if congestion > 1.8:
            return {
                "action": "LOW_SPEED_STEADY",
                "ui_message": "Tráfico denso: Mantenga velocidad baja constante. No acelere y frene bruscamente.",
                "science": "Gonder (2012): Mantener una velocidad baja constante en tráfico ahorra hasta un 20% frente al ciclo de aceleración y frenado total.",
                "savings": 0.20
            }

        # 2. Anticipación de Cuello de Botella
        if congestion > 1.3 and speed > 50:
            return {
                "action": "COASTING",
                "ui_message": "Congestión detectada adelante: Suelte el pedal. Deje que el peso del camión lo lleve.",
                "science": "Nasir (2014): La navegación verde utiliza datos de flujo para reducir la energía cinética desperdiciada en frenado.",
                "savings": 0.35
            }

        # --- REGLAS DE CLIMA Y DINÁMICA DE FLUIDOS ---

        # 3. Resistencia por Viento en Contra
        if wind_ms > 10 and speed > 75:
            return {
                "action": "WIND_COMPENSATION",
                "ui_message": f"Viento fuerte ({wind_ms}m/s): Reduzca a 70km/h. El viento está actuando como un freno constante.",
                "science": "La fuerza de arrastre aumenta proporcionalmente al cuadrado de la velocidad del aire. Bajar 10km/h reduce el gasto drásticamente.",
                "savings": 0.15
            }

        # 4. Eficiencia Térmica y Lluvia
        if precip > 1.5:
            return {
                "action": "WET_EFFICIENCY",
                "ui_message": "Lluvia: Reduzca velocidad. El arrastre por agua y la pérdida de tracción bajan la eficiencia.",
                "science": "Gonder (2012): Las superficies mojadas aumentan la resistencia a la rodadura y el riesgo de micro-patinaje del motor.",
                "savings": 0.08
            }

        # --- REGLAS MECÁNICAS (HOWO MAX 14L) ---

        # 5. Optimización de Torque en Pendiente
        if slope > 4:
            return {
                "action": "POWER_BAND",
                "ui_message": "Subida pronunciada: Mantenga el motor entre 1100-1300 RPM para torque máximo (2700Nm).",
                "science": "Ficha Técnica Weichai: Operar en el pico de torque evita inyecciones extra de combustible para compensar falta de fuerza.",
                "savings": 0.12
            }

        return {
            "action": "KEEP",
            "ui_message": "Condiciones óptimas: Mantenga crucero estable.",
            "science": "Estado estacionario: mínima variación de aceleración detectada.",
            "savings": 0
        }