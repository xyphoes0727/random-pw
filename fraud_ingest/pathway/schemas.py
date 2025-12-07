import pathway as pw


class Transaction(pw.Schema):
    transactionId: str = pw.column_definition(primary_key=True)
    step: int
    type: int
    amount: float
    nameOrig: str
    oldbalanceOrg: float
    newbalanceOrig: float
    nameDest: str
    oldbalanceDest: float
    newbalanceDest: float
    isFraud: int
    kyc_tier: int


class TransactionRaw(pw.Schema):
    transactionId: str = pw.column_definition(primary_key=True)
    step: int
    type: int
    amount: float
    nameOrig: str
    oldbalanceOrg: float
    newbalanceOrig: float
    nameDest: str
    oldbalanceDest: float
    newbalanceDest: float
