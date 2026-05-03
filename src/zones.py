"""
Multi-Zone System - Phase 2.3 (Left-to-Right Slice)
---------------------------------------------------
Bulletproof layout. Prevents 'NoneType' errors by covering infinite resolution.
Left: SAFE | Middle: WARNING | Right: CRITICAL
"""

class SecurityZone:
    def __init__(self, name, coords, level, color):
        self.name = name
        self.coords = coords  # (x1, y1, x2, y2)
        self.level = level    
        self.color = color    

    def contains_point(self, x, y):
        x1, y1, x2, y2 = self.coords
        return x1 <= x <= x2 and y1 <= y <= y2

class ZoneManager:
    def __init__(self):
        self.zones = []
        self._setup_default_zones()

    def _setup_default_zones(self):
        # 🟢 LEFT SIDE - SAFE AREA
        self.add_zone(SecurityZone(
            name="Safe Zone",
            coords=(0, 0, 400, 3000), 
            level="SAFE",
            color=(0, 255, 0)
        ))

        # 🟠 MIDDLE SIDE - BUFFER ZONE
        self.add_zone(SecurityZone(
            name="Warning Zone",
            coords=(400, 0, 800, 3000),
            level="WARNING",
            color=(0, 165, 255)
        ))

        # 🔴 RIGHT SIDE - CRITICAL AREA
        self.add_zone(SecurityZone(
            name="Critical Zone",
            coords=(800, 0, 4000, 3000), 
            level="CRITICAL",
            color=(0, 0, 255)
        ))

    def add_zone(self, zone):
        self.zones.append(zone)

    def get_zone_for_point(self, x, y):
        # Priority: Critical > Warning > Safe
        for zone in reversed(self.zones):
            if zone.contains_point(x, y):
                return zone
        return None

    def draw_all_zones(self, frame, cv2):
        for zone in self.zones:
            x1, y1, x2, y2 = zone.coords
            # Draw line to bottom of standard frame (1080p limit for visualization)
            cv2.rectangle(frame, (x1, y1), (x2, 1080), zone.color, 2)
            label = f"{zone.name} [{zone.level}]"
            cv2.putText(frame, label, (x1 + 10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, zone.color, 2)