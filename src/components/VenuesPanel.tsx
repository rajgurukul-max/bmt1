"use client";

import { useState } from "react";
import { MapPin, IndianRupee, Pencil, ImageOff } from "lucide-react";
import AddVenueModal from "./AddVenueModal";

export default function VenuesPanel({
  venues,
  onVenueUpdated,
  onAddVenue,
}: {
  venues: any[];
  onVenueUpdated: (venue: any) => void;
  onAddVenue: () => void;
}) {
  const [editingVenue, setEditingVenue] = useState<any>(null);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-sm font-medium text-[#9FB0A3] uppercase tracking-wide">
          Your Venues ({venues.length})
        </h2>
      </div>

      {venues.length === 0 ? (
        <div className="bg-[#16291C] border border-[#1E3324] rounded-lg p-8 text-center">
          <p className="text-[#9FB0A3] mb-4">No venues yet</p>
          <button
            onClick={onAddVenue}
            className="bg-[#8BC34A] text-[#0E1F14] px-4 py-2 rounded-md text-sm font-medium"
          >
            Add your first venue
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {venues.map((v) => (
            <div
              key={v.id}
              className="bg-[#16291C] border border-[#1E3324] rounded-xl overflow-hidden"
            >
              <div className="h-32 bg-[#0E1F14] relative">
                {v.photos && v.photos.length > 0 ? (
                  <img
                    src={v.photos[0]}
                    alt={v.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-[#5C7066]">
                    <ImageOff size={24} />
                  </div>
                )}
                {v.photos && v.photos.length > 1 && (
                  <span className="absolute bottom-2 right-2 bg-black/60 text-white text-xs px-2 py-0.5 rounded-full">
                    +{v.photos.length - 1} more
                  </span>
                )}
              </div>
              <div className="p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h3 className="font-semibold text-[#F4F7ED] text-sm">{v.name}</h3>
                    {v.complex_name && (
                      <p className="text-xs text-[#5C7066]">{v.complex_name}</p>
                    )}
                  </div>
                  <button
                    onClick={() => setEditingVenue(v)}
                    className="flex items-center gap-1 text-xs text-[#8BC34A] border border-[#2C4A33] px-2.5 py-1.5 rounded-md hover:border-[#8BC34A] transition-colors"
                  >
                    <Pencil size={12} /> Edit
                  </button>
                </div>
                <div className="flex items-center gap-1 text-xs text-[#9FB0A3] mb-1">
                  <MapPin size={11} />
                  {v.area}{v.city ? `, ${v.city}` : ""}
                </div>
                <div className="flex items-center justify-between mt-3">
                  <span className="text-xs bg-[#8BC34A]/10 text-[#8BC34A] px-2 py-1 rounded-full">
                    {v.sport_type || v.sport}
                  </span>
                  <div className="flex items-center gap-1 font-mono text-sm text-[#F4F7ED]">
                    <IndianRupee size={12} />
                    {v.price_per_hour?.toLocaleString("en-IN")}/hr
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {editingVenue && (
        <AddVenueModal
          venue={editingVenue}
          onClose={() => setEditingVenue(null)}
          onSave={(updated) => {
            onVenueUpdated(updated);
            setEditingVenue(null);
          }}
          existingComplexNames={Array.from(
            new Set(venues.map((v: any) => v.complex_name).filter(Boolean))
          )}
        />
      )}
    </div>
  );
}
