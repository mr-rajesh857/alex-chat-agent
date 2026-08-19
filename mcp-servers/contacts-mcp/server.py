from fastmcp import FastMCP
import httpx
import re

mcp = FastMCP("contacts-mcp")

@mcp.tool()
async def resolve_person(name: str = None, query: str = None, access_token: str = None) -> dict:
    """
    Queries real Google Contacts via Google People API.
    Zero dummy/generated data.
    """
    search_target = name or query or ""
    if not search_target or search_target.lower() in ["contact", "contact details", "person", "find contact"]:
        return {"status": "error", "message": "Please specify the contact name or email address you would like to find."}

    target_lower = search_target.lower()

    if access_token:
        try:
            headers = {"Authorization": f"Bearer {access_token}"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://people.googleapis.com/v1/people/me/connections?pageSize=100&personFields=names,emailAddresses,phoneNumbers",
                    headers=headers
                )
                if resp.status_code == 200:
                    connections = resp.json().get("connections", [])
                    matched = []
                    for p in connections:
                        names = p.get("names", [])
                        displayName = names[0].get("displayName", "") if names else ""
                        emails = p.get("emailAddresses", [])
                        email_val = emails[0].get("value", "") if emails else ""
                        phones = p.get("phoneNumbers", [])
                        phone_val = phones[0].get("value", "") if phones else ""

                        if target_lower in displayName.lower() or (email_val and target_lower in email_val.lower()):
                            matched.append({
                                "name": displayName or search_target.title(),
                                "email": email_val or "No email listed",
                                "phone": phone_val or "No phone listed"
                            })

                    if matched:
                        contact_lines = [f"• **{c['name']}**\n  • Email: {c['email']}\n  • Phone: {c['phone']}" for c in matched]
                        return {
                            "status": "success",
                            "message": f"👤 **Google Contacts Match for '{search_target.title()}'**:\n\n" + "\n\n".join(contact_lines),
                            "contacts": matched
                        }
                    else:
                        return {
                            "status": "success",
                            "message": f"🔍 No contact matching '{search_target.title()}' was found in your Google Contacts.",
                            "contacts": []
                        }
        except Exception:
            pass

    return {
        "status": "error",
        "message": f"🔑 Google Contacts permission required. Please sign in with Google to grant contacts reading permission."
    }

if __name__ == "__main__":
    mcp.run()
