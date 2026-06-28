"""Masters router — CRUD for the legacy master entities (Client, Lead, ...).

Phase 4 fills out the remaining masters (City, Project, Terms, Email Setup) and
their UIs; this covers what the quoting flow and pipeline board need now.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.core.security import get_current_user, require_role
from app.models import Client, Project, Lead, TermsTemplate, EmailSetup, Product
from app.schemas import ClientIn, ProjectIn, LeadIn, TermsIn, EmailSetupIn, ProductUpdate
from app.core.serialize import product_out

router = APIRouter(prefix="/api/masters", tags=["masters"])


# --- Terms templates ---
@router.get("/terms")
def list_terms(db: Session = Depends(get_session), user=Depends(get_current_user)):
    rows = db.execute(select(TermsTemplate)).scalars().all()
    return [{"id": t.id, "name": t.name, "kind": t.kind, "body": t.body} for t in rows]


@router.post("/terms")
def create_terms(body: TermsIn, db: Session = Depends(get_session),
                 user=Depends(get_current_user)):
    t = TermsTemplate(**body.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name}


@router.put("/terms/{terms_id}")
def update_terms(terms_id: int, body: TermsIn, db: Session = Depends(get_session),
                 user=Depends(get_current_user)):
    t = db.get(TermsTemplate, terms_id)
    if not t:
        raise HTTPException(404, "Terms template not found")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return {"id": t.id, "name": t.name}


# --- Email setup (single active row) ---
@router.get("/email-setup")
def get_email_setup(db: Session = Depends(get_session),
                    user=Depends(require_role("manager", "admin"))):
    s = db.execute(select(EmailSetup)).scalars().first()
    if not s:
        return None
    return {"id": s.id, "smtp_host": s.smtp_host, "smtp_port": s.smtp_port,
            "username": s.username, "from_email": s.from_email, "use_tls": s.use_tls}


@router.put("/email-setup")
def save_email_setup(body: EmailSetupIn, db: Session = Depends(get_session),
                     user=Depends(require_role("manager", "admin"))):
    s = db.execute(select(EmailSetup)).scalars().first()
    if s:
        for k, v in body.model_dump().items():
            setattr(s, k, v)
    else:
        s = EmailSetup(**body.model_dump())
        db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "from_email": s.from_email}


# --- Product pricing edits (manager/admin) ---
@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_session),
                   user=Depends(require_role("manager", "admin"))):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    # Editing pricing params makes the migrated override snapshot stale.
    p.is_manual_override = False
    p.migrated_client_unit = None
    p.migrated_final_c2e = None
    db.commit()
    return product_out(p, include_cost=True)


# --- Clients ---
@router.get("/clients")
def list_clients(db: Session = Depends(get_session), user=Depends(get_current_user)):
    rows = db.execute(select(Client).order_by(Client.name)).scalars().all()
    return [{"id": c.id, "name": c.name, "email": c.email, "phone": c.phone,
             "city": c.city, "address": c.address, "gstin": c.gstin} for c in rows]


@router.post("/clients")
def create_client(body: ClientIn, db: Session = Depends(get_session),
                  user=Depends(get_current_user)):
    c = Client(**body.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name}


@router.put("/clients/{client_id}")
def update_client(client_id: int, body: ClientIn, db: Session = Depends(get_session),
                  user=Depends(get_current_user)):
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(404, "Client not found")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return {"id": c.id, "name": c.name}


@router.delete("/clients/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_session),
                  user=Depends(require_role("manager", "admin"))):
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(404, "Client not found")
    n = db.execute(select(Project).where(Project.client_id == client_id)).scalars().all()
    if n:
        raise HTTPException(400, f"Cannot delete: {len(n)} project(s) still belong to this client")
    db.delete(c)
    db.commit()
    return {"deleted": client_id}


# --- Projects ---
@router.get("/projects")
def list_projects(client_id: int | None = None, db: Session = Depends(get_session),
                  user=Depends(get_current_user)):
    q = select(Project).order_by(Project.name)
    if client_id is not None:
        q = q.where(Project.client_id == client_id)
    rows = db.execute(q).scalars().all()
    return [{"id": p.id, "name": p.name, "client_id": p.client_id, "city": p.city} for p in rows]


@router.post("/projects")
def create_project(body: ProjectIn, db: Session = Depends(get_session),
                   user=Depends(get_current_user)):
    if not db.get(Client, body.client_id):
        raise HTTPException(404, "Client not found")
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "name": p.name}


@router.put("/projects/{project_id}")
def update_project(project_id: int, body: ProjectIn, db: Session = Depends(get_session),
                   user=Depends(get_current_user)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    if not db.get(Client, body.client_id):
        raise HTTPException(404, "Client not found")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return {"id": p.id, "name": p.name}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_session),
                   user=Depends(require_role("manager", "admin"))):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    n = db.execute(select(Lead).where(Lead.project_id == project_id)).scalars().all()
    if n:
        raise HTTPException(400, f"Cannot delete: {len(n)} lead(s) still belong to this project")
    db.delete(p)
    db.commit()
    return {"deleted": project_id}


# --- Leads / pipeline ---
@router.get("/leads")
def list_leads(db: Session = Depends(get_session), user=Depends(get_current_user)):
    rows = db.execute(select(Lead).order_by(Lead.stage)).scalars().all()
    return [{"id": l.id, "name": l.name, "owner": l.owner, "stage": l.stage,
             "amount": l.amount, "project_id": l.project_id, "client_id": l.client_id}
            for l in rows]


@router.post("/leads")
def create_lead(body: LeadIn, db: Session = Depends(get_session),
                user=Depends(get_current_user)):
    project = db.get(Project, body.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    l = Lead(**body.model_dump(), client_id=project.client_id)
    db.add(l)
    db.commit()
    db.refresh(l)
    return {"id": l.id, "name": l.name, "stage": l.stage}


@router.put("/leads/{lead_id}")
def update_lead(lead_id: int, body: LeadIn, db: Session = Depends(get_session),
                user=Depends(get_current_user)):
    l = db.get(Lead, lead_id)
    if not l:
        raise HTTPException(404, "Lead not found")
    project = db.get(Project, body.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    for k, v in body.model_dump().items():
        setattr(l, k, v)
    l.client_id = project.client_id
    db.commit()
    return {"id": l.id, "name": l.name, "stage": l.stage}


@router.delete("/leads/{lead_id}")
def delete_lead(lead_id: int, db: Session = Depends(get_session),
                user=Depends(require_role("manager", "admin"))):
    l = db.get(Lead, lead_id)
    if not l:
        raise HTTPException(404, "Lead not found")
    db.delete(l)
    db.commit()
    return {"deleted": lead_id}


@router.patch("/leads/{lead_id}/stage")
def move_lead(lead_id: int, stage: int, db: Session = Depends(get_session),
              user=Depends(get_current_user)):
    l = db.get(Lead, lead_id)
    if not l:
        raise HTTPException(404, "Lead not found")
    if stage not in (0, 1, 2, 3):
        raise HTTPException(422, "stage must be 0..3")
    l.stage = stage
    db.commit()
    return {"id": l.id, "stage": l.stage}
