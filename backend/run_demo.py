import uvicorn
from app.main import create_app
from app.operations import InMemoryOperationsStore

app = create_app(operations_store=InMemoryOperationsStore())

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
