import os
import csv
import sys
import requests

SHOP = os.environ["SHOP"]  # e.g. misquoters.myshopify.com
TOKEN = os.environ["SHOPIFY_TOKEN"]  # shpat_...
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-01")

# Where your "author" lives (Shopify product metafield)
AUTHOR_NAMESPACE = os.environ.get("AUTHOR_NAMESPACE", "custom")
AUTHOR_KEY = os.environ.get("AUTHOR_KEY", "author")

# Which Meta label column you want to fill (custom_label_0..custom_label_4)
META_LABEL_COL = os.environ.get("META_LABEL_COL", "custom_label_0")

OUT_CSV = os.environ.get("OUT_CSV", "meta_supplemental_feed.csv")

GRAPHQL_URL = f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json",
}

QUERY = """
query ProductsWithAuthor($cursor: String) {
  products(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        metafield(namespace: "%s", key: "%s") { value }
        variants(first: 100) {
          edges {
            node {
              id
              legacyResourceId
            }
          }
        }
      }
    }
  }
}
""" % (AUTHOR_NAMESPACE, AUTHOR_KEY)

def gql(variables):
    r = requests.post(GRAPHQL_URL, headers=HEADERS, json={"query": QUERY, "variables": variables}, timeout=60)
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

    while True:
        data = gql({"cursor": cursor})
        products = data["products"]
        total_products += len(products["edges"])

        for edge in products["edges"]:
            p = edge["node"]
            author = ""
            if p.get("metafield") and p["metafield"] and p["metafield"].get("value"):
                author = str(p["metafield"]["value"]).strip()

            # If no author, skip (or you can write blank rows—Meta usually prefers fewer rows)
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

    # Write CSV
    fieldnames = ["id", META_LABEL_COL]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"✅ Wrote {OUT_CSV}")
    print(f"Products scanned: {total_products}")
    print(f"Rows written (variants with author): {total_variants}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ ERROR:", e)
        sys.exit(1)
