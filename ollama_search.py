"""WB-053 governed web knowledge adapter for Ollama.

Reusable DDGS retrieval for the governance knowledge resolver plus a small CLI.
Internet material is advisory knowledge only; it is never organisational evidence.
"""
from __future__ import annotations
import datetime as dt
import os
import re
from typing import Any

DEFAULT_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3.1:8b')
CURRENT_DATE = dt.date.today().strftime('%B %d, %Y')
CURRENT_YEAR = dt.date.today().year
LIVE_KEYWORDS = (
    'current','currently','now','today','latest','recent','this year','this month','this week',
    'president','prime minister','minister','ceo','leader','news','election','elected',
    'weather','temperature','forecast','rain','raining','stock price','share price','exchange rate',
    'latest version','current version','regulation','regulatory','guidance','consultation',
    'effective date','in force','supervisory','amendment','regulatory change','standard update',
)

def needs_internet(text: str) -> bool:
    q=str(text or '').lower()
    return any(k in q for k in LIVE_KEYWORDS) or bool(re.search(r'\b20\d{2}\b', q))

def search_web(query: str, max_results: int = 5) -> list[dict[str,str]]:
    """Rows only. Kept for callers that do not care why a search came back empty."""
    rows, _ = search_web_checked(query, max_results=max_results)
    return rows


def search_web_checked(query: str, max_results: int = 5) -> tuple[list[dict[str,str]], str|None]:
    """WB-056: rows AND the reason there are none.

    The previous version caught every exception and returned []. A missing `ddgs`, a blocked
    network and a genuinely quiet search were therefore indistinguishable — and because the
    resolver wrapped this in a second bare except, an assessment could be shaped by no external
    knowledge at all with nothing anywhere saying so. Two swallows in series is how a dead
    feature looks healthy.

    Returns (rows, error). `error` is None when the search ran, whether or not it found
    anything: no results is a result, and must stay distinguishable from no search.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return [], ("the ddgs package is not installed, so no web search was performed - "
                    "pip install 'ddgs>=9.0'")
    try:
        rows=[]
        with DDGS() as ddgs:
            for result in ddgs.text(str(query), max_results=max(1,int(max_results))):
                row={'title':str(result.get('title','')).strip(),'snippet':str(result.get('body','')).strip(),'url':str(result.get('href','')).strip()}
                if row['title'] or row['snippet'] or row['url']:
                    rows.append(row)
        return rows, None
    except Exception as exc:
        return [], f"the web search failed ({type(exc).__name__}: {exc})"

def search_context(query: str, max_results: int = 5) -> dict[str,Any]:
    rows,error=search_web_checked(query,max_results=max_results)
    return {'query':query,'retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
            'source_type':'internet','results':rows,'used':bool(rows),
            'searched':error is None,'error':error}

def format_results(rows: list[dict[str,str]]) -> str:
    if not rows:
        return '(no external web knowledge retrieved)'
    parts=[]
    for i,row in enumerate(rows,1):
        parts.append(f"SOURCE [{i}]\n\nTitle:\n{row['title']}\n\nInformation:\n{row['snippet']}\n\nURL:\n{row['url']}")
    return '\n\n'.join(parts)

def ask_ollama(system: str, user: str, *, model: str|None=None) -> str:
    import requests
    r=requests.post(f"{os.environ.get('OLLAMA_URL','http://localhost:11434')}/api/chat",timeout=300,json={
        'model':model or DEFAULT_MODEL,'stream':False,'think':False,
        'options':{'temperature':0,'seed':7,'num_ctx':32768},
        'messages':[{'role':'system','content':system},{'role':'user','content':user}],
    })
    r.raise_for_status()
    return str(r.json()['message']['content'])

def main() -> None:
    print('GOVERNED OLLAMA WEB-KNOWLEDGE AGENT')
    print('Model:',os.environ.get('OLLAMA_MODEL',DEFAULT_MODEL))
    print('Date:',CURRENT_DATE)
    print('Web results are advisory knowledge, never audit evidence.')
    print("Type 'exit' to quit.")
    history=[]
    while True:
        try:
            question=input('\nYou: ').strip()
        except (KeyboardInterrupt,EOFError):
            print('\nExiting...'); return
        if question.lower()=='exit': return
        if not question: continue
        if needs_internet(question):
            query=question if str(CURRENT_YEAR) in question else f'{question} {CURRENT_YEAR}'
            ctx=search_context(query,int(os.environ.get('WB_WEB_MAX_RESULTS','5')))
            print('\nROUTER: INTERNET KNOWLEDGE')
            print(format_results(ctx['results']))
            prompt=f"Today's date is {CURRENT_DATE}.\n\nUser question:\n{question}\n\nAdvisory web knowledge:\n{format_results(ctx['results'])}\n\nAnswer carefully. Do not invent facts. If sources conflict or are insufficient, say so."
            try: print('\nAI:\n'+ask_ollama('You are a careful governance knowledge assistant.',prompt))
            except Exception as exc: print('\nERROR:',exc)
        else:
            print('\nROUTER: LOCAL MODEL')
            history.append({'role':'user','content':question})
            try:
                prompt='\n'.join(f"{m['role']}: {m['content']}" for m in history)
                answer=ask_ollama('You are a careful governance knowledge assistant.',prompt)
                history.append({'role':'assistant','content':answer})
                print('\nAI:\n'+answer)
            except Exception as exc: print('\nERROR:',exc)

if __name__=='__main__': main()
