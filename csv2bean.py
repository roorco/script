from beancount.ingest import importer
from beancount.core import data, amount
from datetime import datetime
import csv

class AXAImporter(importer.ImporterProtocol):
    def identify(self, file):
        # Riconosci solo i CSV di AXA
        return file.name.lower().endswith("axa_2025.csv")

    def extract(self, file):
        entries = []
        with open(file.name, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Parsing base
                date = datetime.strptime(row["Date"], "%d/%m/%Y").date()
                desc = row["Description"].strip()
                amt = float(row["Amount"].replace(",", ".").replace("€", ""))

                # Conti di default
                account1 = "Assets:Bank:AXA"
                account2 = "Expenses:Misc"

                # Regole condizionali equivalenti alle tue 'if'
                if "DDFIP" in desc:
                    account2 = "Expenses:Purchases:DDFIP"
                elif "DECATHLON" in desc:
                    account2 = "Expenses:Purchases:Decathlon"
                elif "LIDL" in desc:
                    account2 = "Expenses:Groceries"
                elif "BOULANG" in desc:
                    account2 = "Expenses:Purchases:Boulangerie"
                elif "RELAIS PRODUCTEU" in desc:
                    account2 = "Expenses:Groceries"
                elif "CARREFOUR" in desc:
                    account2 = "Expenses:Purchases:Groceries"
                elif "VIR INST vers Lucie Laporte" in desc:
                    account2 = "Assets:Lucie"
                elif "GRAINE" in desc:
                    account2 = "Expenses:Groceries"
                elif "IKEA" in desc or "LEROY" in desc:
                    account2 = "Expenses:Purchases:Home"
                elif "STRIKE" in desc:
                    account1 = "Assets:Bank:AXA"
                    account2 = "Assets:Strike"
                elif "VIR MELLE LAPORTE" in desc:
                    account2 = "Assets:Bank:Lucie"
                elif "NAVIGO" in desc:
                    account2 = "Expenses:Services:Transport"
                elif "15 INFROIT" in desc:
                    account2 = "Expenses:Home:Copropriete"
                elif "VIR vers LIVRET" in desc:
                    account1 = "Assets:Bank:AXA"
                    account2 = "Equity:Bank:Livret"
                elif "VIR de LIVRET" in desc:
                    account1 = "Assets:Bank:AXA"
                    account2 = "Equity:Bank:Livret"
                elif "VIR vers Lucie" in desc:
                    account2 = "Assets:Bank:Lucie"

                # Crea la transazione
                meta = data.new_metadata(file.name, 0)
                txn = data.Transaction(
                    meta=meta,
                    date=date,
                    flag="*",
                    payee=None,
                    narration=desc,
                    postings=[
                        data.Posting(account1, amount.Amount(amt, "EUR"), None, None, None, None),
                        data.Posting(account2, None, None, None, None, None),
                    ],
                )
                entries.append(txn)

        return entries

    def file_name(self, file):
        return "axa_import.beancount"
