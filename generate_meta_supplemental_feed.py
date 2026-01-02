import os
import csv
import sys
import requests

# ---- ENV (strip everything to avoid hidden whitespace/newlines) ----
SHOP = os.environ["SHOP"].strip()  # e.g. misquoters.myshopify.com

TOKEN = os.environ.get("SHOPIFY_TOKEN", "").strip()

CLIENT_ID = os.environ.get("CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "").strip()

API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-01").strip()

AUTHOR_NAMESPACE = os.environ.get("AUTHOR_NAMESPACE", "custom").strip()
AUTHOR_KEY = os.environ.get("AUTHOR_KEY", "author").strip()

META_LABEL_COL = os.environ.get("META_LABEL_COL", "custom_label_0").strip()

OUT_CSV = os.environ.get("OUT_CSV", "meta_supplemental_feed.csv").strip()


def get_access_token():
    """
    Get a fresh Admin API access token using Shopify client credentials.
    Requires CLIENT_ID + CLIENT_SECRET.
    """
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("Missing CLIENT_ID or CLIENT_SECRET (GitHub secrets).")

    token_url = f"https://{SHOP}/admin/oauth/access_token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "read_products",
    }
    r = requests.post(token_url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token response did not include access_token: {data}")
    return data["access_token"]


if not TOKEN:
    TOKEN = get_access_token()

GRAPHQL_URL = f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json",
}

# We query both:
# - metafield(namespace,key) for the exact lookup
# - metafields(namespace:first...) for DEBUG visibility if rows end up 0
QUERY = f"""
query ProductsWithAuthor($cursor: String) {{
  products(first: 100, after: $cursor) {{
    pageInfo {{ hasNextPage endCursor }}
    edges {{
      node {{
        id
        title
        metafield(namespace: "{AUTHOR_NAMESPACE}", key: "{AUTHOR_KEY}") {{ value }}

        # Debug: show what metafields exist in this namespace
        metafields(first: 20, namespace: "{AUTHOR_NAMESPACE}") {{
          edges {{
            node {{ namespace key value }}
          }}
        }}

        variants(first: 100) {{
          edges {{
            node {{
              legacyResourceId
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""


def gql(variables):
    r = requests.post(
        GRAPHQL_URL,
        headers=HEADERS,
        json={"query": QUERY, "variables": variables},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def main():
    rows = []
    cursor = None
    total_products = 0
    total_variants = 0

    # Keep a small debug sample to print if we get 0 rows
    debug_samples = []

    while True:
        data = gql({"cursor": cursor})
        products = data["products"]
        total_products += len(products["edges"])

        for edge in products["edges"]:
            p = edge["node"]

            mf = p.get("metafield")
            author = (mf.get("value") if mf else "") or ""
            author = str(author).strip()

            # capture a few debug samples
            if len(debug_samples) < 5:
                ns_mfs = p.get("metafields", {}).get("edges", [])
                debug_samples.append({
                    "title": p.get("title", ""),
                    "exact_lookup_value": author,
                    "namespace_metafields": [
                        f'{e["node"]["namespace"]}.{e["node"]["key"]}={e["node"]["value"]}'
                        for e in ns_mfs
                    ],
                })

            if not author:
                continue

            for v_edge in p["variants"]["edges"]:
                v = v_edge["node"]
                variant_id = v.get("legacyResourceId")
                if not variant_id:
                    continue

                rows.append({
                    "id": str(variant_id),
                    META_LABEL_COL: author
                })
                total_variants += 1

        if not products["pageInfo"]["hasNextPage"]:
            break
        cursor = products["pageInfo"]["endCursor"]

    fieldnames = ["id", META_LABEL_COL]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"✅ Wrote {OUT_CSV}")
    print(f"Products scanned: {total_products}")
    print(f"Rows written (variants with author): {total_variants}")

    if total_variants == 0:
        print("\n--- DEBUG (first 5 products) ---")
        print(f"Looking for metafield: {AUTHOR_NAMESPACE}.{AUTHOR_KEY}")
        for s in debug_samples:
            print(f'\nProduct: {s["title"]}')
            print(f'Exact lookup value: {s["exact_lookup_value"]!r}')
            print("Metafields in namespace:")
            for line in s["namespace_metafields"]:
                print(f"  - {line}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ ERROR:", e)
        sys.exit(1)
