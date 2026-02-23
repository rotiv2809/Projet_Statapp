from app.agents.router_agent import route_message

tests = [
    "Delete all transaction from 2024",
    "Top 10 communes",
    "Top 10 communes by number of clients in 2024",
    "How many clients are there by segment_client?",
    "Explain what SQL is "
    "SELCT * From clients; Drop TABLE clients;"

]

for t in tests:
    d = route_message(t)
    print("\nQ:",t)
    print("->", d.route,d.reason, "|", d.clarifying_question)