// The website's go-between for importing a deck from a link (see deck_links.py). Browsers may
// only read sites that allow it, and deck sites don't, so the website asks this function,
// which fetches the list server-side. Only Archidekt's deck API and MTGGoldfish's deck download
// are allowed, so it can't be used to fetch anything else.
//
// Deploy once (Supabase CLI, from the repo folder):
//   supabase functions deploy deck-link --no-verify-jwt --project-ref aepdyzawmgpwcmxytocu

const ALLOWED = [
  /^https:\/\/archidekt\.com\/api\/decks\/\d+\/$/,
  /^https:\/\/www\.mtggoldfish\.com\/deck\/download\/\d+$/,
];
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
};

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response(null, { headers: CORS });
  }
  const target = new URL(request.url).searchParams.get("url") ?? "";
  if (!ALLOWED.some((pattern) => pattern.test(target))) {
    return new Response("Only Archidekt and MTGGoldfish deck links can be fetched.", { status: 400, headers: CORS });
  }
  const response = await fetch(target, {
    headers: { "User-Agent": "MultiversalManager/1.0 (github.com/LightInUmbra/multiversal-manager)" },
  });
  return new Response(await response.text(), {
    status: response.status,
    headers: { ...CORS, "Content-Type": response.headers.get("content-type") ?? "text/plain" },
  });
});
