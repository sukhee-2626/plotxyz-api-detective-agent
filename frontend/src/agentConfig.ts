export type FieldType = "text" | "textarea" | "number" | "checkbox";

export interface AgentField {
  name: string;
  label: string;
  type: FieldType;
  rows?: number;
  placeholder?: string;
}

export interface AgentConfig {
  slug: string;
  title: string;
  tagline: string;
  purpose: string;
  accent: string;
  features: string[];
  limitations: string[];
  fields: AgentField[];
  sample: Record<string, string | number | boolean>;
  repo: string;
}

export const agent: AgentConfig = {
  "slug": "plotxyz-api-detective-agent",
  "title": "API Detective",
  "tagline": "Turn a confusing API failure into a next step.",
  "purpose": "Explains common HTTP failures from supplied request and response details, with targeted checks for auth, permissions, rate limits, CORS, and timeouts.",
  "accent": "#e879f9",
  "features": [
    "Status-class explanation",
    "Response-body signal detection",
    "Prioritized debugging checklist"
  ],
  "limitations": [
    "No network request is made; the diagnosis depends on supplied details.",
    "It cannot inspect server logs or provider internals."
  ],
  "fields": [
    {
      "name": "method",
      "label": "HTTP method",
      "type": "text",
      "rows": 4,
      "placeholder": ""
    },
    {
      "name": "url",
      "label": "Request URL",
      "type": "text",
      "rows": 4,
      "placeholder": ""
    },
    {
      "name": "status",
      "label": "Status code",
      "type": "number",
      "rows": 4,
      "placeholder": ""
    },
    {
      "name": "response_body",
      "label": "Response body",
      "type": "textarea",
      "rows": 5,
      "placeholder": ""
    }
  ],
  "sample": {
    "method": "GET",
    "url": "https://api.example.com/v1/orders/42",
    "status": 401,
    "response_body": "{\"error\":\"token expired\"}"
  },
  "repo": "https://github.com/sukhee-2626/plotxyz-api-detective-agent"
};
