'use client'
import { useState } from "react";
import SriLankaMap from "./SriLankaMap";
import DistrictInfoPanel from "./DistrictInfoPanel";
import { Card } from "../ui/card";
import { MapPin, Activity } from "lucide-react";
import { useRogerData } from "../../hooks/use-roger-data";
import { Badge } from "../ui/badge";

const MapView = () => {
  const [selectedDistrict, setSelectedDistrict] = useState<string | null>(null);
  const { events, isConnected } = useRogerData();

  // Province to districts mapping
  const provinceToDistricts: Record<string, string[]> = {
    "western province": ["Colombo", "Gampaha", "Kalutara"],
    "western": ["Colombo", "Gampaha", "Kalutara"],
    "central province": ["Kandy", "Matale", "Nuwara Eliya"],
    "central": ["Kandy", "Matale", "Nuwara Eliya"],
    "southern province": ["Galle", "Matara", "Hambantota"],
    "southern provinces": ["Galle", "Matara", "Hambantota"],
    "southern": ["Galle", "Matara", "Hambantota"],
    "south": ["Galle", "Matara", "Hambantota"],
    "northern province": ["Jaffna", "Kilinochchi", "Mannar", "Vavuniya", "Mullaitivu"],
    "northern": ["Jaffna", "Kilinochchi", "Mannar", "Vavuniya", "Mullaitivu"],
    "north": ["Jaffna", "Kilinochchi", "Mannar", "Vavuniya", "Mullaitivu"],
    "eastern province": ["Batticaloa", "Ampara", "Trincomalee"],
    "eastern": ["Batticaloa", "Ampara", "Trincomalee"],
    "east": ["Batticaloa", "Ampara", "Trincomalee"],
    "north western province": ["Kurunegala", "Puttalam"],
    "north western": ["Kurunegala", "Puttalam"],
    "north central province": ["Anuradhapura", "Polonnaruwa"],
    "north central": ["Anuradhapura", "Polonnaruwa"],
    "uva province": ["Badulla", "Moneragala"],
    "uva": ["Badulla", "Moneragala"],
    "sabaragamuwa province": ["Ratnapura", "Kegalle"],
    "sabaragamuwa": ["Ratnapura", "Kegalle"],
  };

  const allDistricts = [
    'Colombo', 'Gampaha', 'Kandy', 'Jaffna', 'Galle', 'Matara', 'Hambantota',
    'Anuradhapura', 'Polonnaruwa', 'Batticaloa', 'Ampara', 'Trincomalee',
    'Kurunegala', 'Puttalam', 'Kalutara', 'Ratnapura', 'Kegalle', 'Nuwara Eliya',
    'Badulla', 'Moneragala', 'Kilinochchi', 'Mannar', 'Vavuniya', 'Mullaitivu', 'Matale'
  ];

  // Count alerts per district with province awareness
  const districtAlertCounts: Record<string, number> = {};

  (events ?? []).forEach(event => {
    const summary = (event.summary ?? '').toLowerCase();
    const matchedDistricts = new Set<string>();

    // Check for direct district mentions
    allDistricts.forEach(district => {
      if (summary.includes(district.toLowerCase())) {
        matchedDistricts.add(district);
      }
    });

    // Check for province mentions and add their districts
    for (const [province, districts] of Object.entries(provinceToDistricts)) {
      if (summary.includes(province)) {
        districts.forEach(d => matchedDistricts.add(d));
      }
    }

    // Count for each matched district
    matchedDistricts.forEach(district => {
      districtAlertCounts[district] = (districtAlertCounts[district] || 0) + 1;
    });
  });

  // Count critical events
  const criticalEvents = events.filter(e => e.severity === 'critical' || e.severity === 'high');

  return (
    <div className="space-y-4">
      <Card className="p-4 sm:p-6 bg-card border-border">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <MapPin className="w-5 h-5 text-primary" />
            <h2 className="text-base sm:text-lg font-bold">TERRITORY MAP</h2>
          </div>
          <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
            {isConnected ? (
              <Badge className="bg-success/20 text-success flex items-center gap-2 text-xs">
                <span className="w-2 h-2 rounded-full bg-success animate-pulse"></span>
                Live
              </Badge>
            ) : (
              <Badge className="bg-warning/20 text-warning text-xs">Reconnecting...</Badge>
            )}
            <Badge className="border border-border flex items-center gap-2 text-xs">
              <Activity className="w-3 h-3" />
              {criticalEvents.length} Critical
            </Badge>
            <span className="text-xs font-mono text-muted-foreground hidden sm:inline">
              Click any district for detailed intelligence
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6">
          <div className="lg:col-span-2 order-1">
            <div className="h-[350px] sm:h-[450px] lg:h-[550px] w-full">
              <SriLankaMap
                selectedDistrict={selectedDistrict}
                onDistrictSelect={setSelectedDistrict}
                alertCounts={districtAlertCounts}
                className="w-full h-full"
              />
            </div>
          </div>


          <div className="lg:col-span-1 order-2">
            <DistrictInfoPanel district={selectedDistrict} />
          </div>
        </div>
      </Card>
    </div>
  );
};

export default MapView;
