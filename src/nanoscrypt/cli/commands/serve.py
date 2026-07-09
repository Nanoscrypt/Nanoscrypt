import uvicorn
import typer

def serve_cmd(
    host: str = typer.Option("127.0.0.1", help="Host address to bind to"),
    port: int = typer.Option(8000, help="Port to run the API server on"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload for development")
):
    """Starts the FastAPI API server."""
    typer.echo(f"Starting server at http://{host}:{port}/ ...")
    uvicorn.run(
        "nanoscrypt.api.app:app",
        host=host,
        port=port,
        reload=reload
    )
