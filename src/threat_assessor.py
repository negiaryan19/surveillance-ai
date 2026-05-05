class ThreatAssessor:
    def __init__(self):
        # Base threat score limits
        self.MIN_SCORE = 0
        self.MAX_SCORE = 100

    def calculate_threat(self, zone_level, object_type, face_status, is_anomaly):
        """
        Calculates a dynamic threat score based on multiple sensor inputs.
        Returns: (final_score, threat_category, reasons_list)
        """
        score = 0
        reasons = []

        # 1. Zone Analysis (Where is the intruder?)
        if zone_level == "CRITICAL":
            score += 40
            reasons.append("Breached Critical Zone")
        elif zone_level == "PERIMETER":
            score += 20
            reasons.append("In Perimeter")
        elif zone_level == "SAFE":
            reasons.append("In Safe Zone")

        # 2. Object Type Analysis (What is the intruder?)
        if object_type == "Person":
            score += 30
        elif object_type in ["Car", "Motorcycle"]:
            score += 40
            reasons.append("Vehicle Detected")
        elif object_type == "Dog":
            score += 10
            reasons.append("Animal Detected")

        # 3. Face / Identity Analysis (Only applicable for Persons)
        if object_type == "Person":
            if face_status == "KNOWN":
                score -= 50  # Friendly, massive reduction in threat
                reasons.append("Authorized Personnel")
            elif face_status == "SPOOF":
                score += 50  # Extremely suspicious
                reasons.append("Spoofing Attempt Detected")
            else: 
                # UNKNOWN
                score += 20
                reasons.append("Unknown Identity")

        # 4. Behavioral / Anomaly Analysis (What are they doing?)
        if is_anomaly:
            score += 40
            reasons.append("Anomalous/Suspicious Behavior")

        # Clamp score mathematically between 0 and 100
        final_score = max(self.MIN_SCORE, min(self.MAX_SCORE, score))

        # Determine Threat Category
        if final_score < 30:
            category = "LOW"       # Ignore or just log
        elif final_score < 70:
            category = "WARNING"   # Silent Telegram Alert
        else:
            category = "CRITICAL"  # Record Video, Sound Alarm, Telegram Alert

        return final_score, category, reasons