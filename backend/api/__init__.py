from backend.api.analysis import router as analysis_router
from backend.api.comparison import router as comparison_router
from backend.api.reports import router as reports_router
from backend.api.upload import router as upload_router

__all__ = [
    "analysis_router",
    "comparison_router",
    "reports_router",
    "upload_router",
]
