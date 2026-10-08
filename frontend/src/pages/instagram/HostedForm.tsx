import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle, Loader2 } from "lucide-react";

interface Phase2Field {
  field_key: string;
  label: string;
  field_type: string;
  required: boolean;
  options: { value: string; label: string }[];
  placeholder: string;
}

interface Branch {
  id: number;
  name: string;
}

interface FormData {
  form_name: string;
  phase1_data: Record<string, string>;
  phase2_fields: Phase2Field[];
  branches: Branch[];
  status: string;
}

export default function HostedForm() {
  const { formId, token } = useParams<{ formId: string; token: string }>();
  const [data, setData] = useState<FormData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [phase2Values, setPhase2Values] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch(`/api/v1/instagram/forms/${formId}/public?token=${encodeURIComponent(token ?? "")}`)
      .then((res) => {
        if (!res.ok) throw new Error("Form not found or already completed");
        return res.json();
      })
      .then((d) => {
        if (d.status === "completed") setCompleted(true);
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [formId, token]);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const res = await fetch(
        `/api/v1/instagram/forms/${formId}/submit?token=${encodeURIComponent(token ?? "")}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phase2_data: phase2Values }),
        }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : "Submission failed");
      }
      setCompleted(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const renderField = (field: Phase2Field) => {
    const value = phase2Values[field.field_key] || "";

    if (field.field_type === "select" || field.field_type === "dropdown") {
      return (
        <select
          value={value}
          onChange={(e) => setPhase2Values({ ...phase2Values, [field.field_key]: e.target.value })}
          required={field.required}
          className="w-full px-4 py-3 rounded-xl bg-[#1a1c2e] border border-white/10 text-white text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">{field.placeholder || `Select ${field.label}`}</option>
          {field.options.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      );
    }

    if (field.field_type === "date") {
      return (
        <input
          type="date"
          value={value}
          onChange={(e) => setPhase2Values({ ...phase2Values, [field.field_key]: e.target.value })}
          required={field.required}
          className="w-full px-4 py-3 rounded-xl bg-[#1a1c2e] border border-white/10 text-white text-sm focus:outline-none focus:border-blue-500"
        />
      );
    }

    if (field.field_type === "phone") {
      return (
        <input
          type="tel"
          value={value}
          onChange={(e) => setPhase2Values({ ...phase2Values, [field.field_key]: e.target.value })}
          required={field.required}
          placeholder={field.placeholder}
          className="w-full px-4 py-3 rounded-xl bg-[#1a1c2e] border border-white/10 text-white text-sm focus:outline-none focus:border-blue-500"
        />
      );
    }

    return (
      <input
        type="text"
        value={value}
        onChange={(e) => setPhase2Values({ ...phase2Values, [field.field_key]: e.target.value })}
        required={field.required}
        placeholder={field.placeholder}
        className="w-full px-4 py-3 rounded-xl bg-[#1a1c2e] border border-white/10 text-white text-sm focus:outline-none focus:border-blue-500"
      />
    );
  };

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", background: "#0d0f1a", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Loader2 className="animate-spin text-blue-400" size={32} />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ minHeight: "100vh", background: "#0d0f1a", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="text-center">
          <p className="text-red-400 text-sm font-semibold">{error}</p>
        </div>
      </div>
    );
  }

  if (completed) {
    return (
      <div style={{ minHeight: "100vh", background: "#0d0f1a", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="text-center space-y-3">
          <CheckCircle className="text-emerald-400 mx-auto" size={48} />
          <h2 className="text-xl font-bold text-white">Booking Confirmed</h2>
          <p className="text-sm text-gray-400">Thank you! We'll be in touch soon.</p>
        </div>
      </div>
    );
  }

  if (!data || data.phase2_fields.length === 0) {
    return (
      <div style={{ minHeight: "100vh", background: "#0d0f1a", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="text-center">
          <p className="text-sm text-gray-400">No additional fields required.</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0d0f1a", display: "flex", alignItems: "center", justifyContent: "center", padding: "24px" }}>
      <div className="w-full max-w-md space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-white">{data.form_name}</h1>
          <p className="text-sm text-gray-400 mt-1">Complete your booking</p>
        </div>

        {Object.keys(data.phase1_data).length > 0 && (
          <div className="rounded-2xl bg-[#1a1c2e] border border-white/10 p-4 space-y-2">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Your Details</p>
            {Object.entries(data.phase1_data).map(([key, val]) => (
              <div key={key} className="flex justify-between text-sm">
                <span className="text-gray-400 capitalize">{key.replace(/_/g, " ")}</span>
                <span className="text-white font-medium">{val}</span>
              </div>
            ))}
          </div>
        )}

        <div className="rounded-2xl bg-[#1a1c2e] border border-white/10 p-5 space-y-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Select Your Options</p>
          {data.phase2_fields.map((field) => (
            <div key={field.field_key}>
              <label className="text-xs font-semibold text-gray-300 mb-1.5 block">
                {field.label} {field.required && <span className="text-red-400">*</span>}
              </label>
              {renderField(field)}
            </div>
          ))}
        </div>

        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="w-full py-3 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 transition-colors disabled:opacity-50"
        >
          {submitting ? "Submitting..." : "Confirm Booking"}
        </button>
      </div>
    </div>
  );
}
