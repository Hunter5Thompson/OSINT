import {fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import {BriefingPage} from '../../pages/BriefingPage';
import {createReport, deleteReport} from '../../services/api';

vi.mock('../../hooks/useIntel',()=>({useIntel:()=>({
  loading:false,currentAgent:null,result:null,error:null,runQuery:vi.fn(()=>vi.fn()),
})}));

afterEach(()=>vi.unstubAllGlobals());

describe('report write errors',()=>{
  it('shows the backend configuration reason after New Dossier fails, without creating a phantom dossier',async()=>{
    const fetchMock=vi.fn(async (_input:RequestInfo|URL, init?:RequestInit)=>{
      if(init?.method==='POST')return new Response(JSON.stringify({detail:'reports admin token not configured'}),
        {status:503,statusText:'Service Unavailable',headers:{'Content-Type':'application/json'}});
      return new Response('[]',{status:200,headers:{'Content-Type':'application/json'}});
    });
    vi.stubGlobal('fetch',fetchMock);
    render(<MemoryRouter><BriefingPage/></MemoryRouter>);
    await screen.findByText(/no dossiers yet/);
    fireEvent.click(screen.getByRole('button',{name:/New Dossier/}));
    expect(await screen.findByText(/reports admin token not configured/)).toBeInTheDocument();
    expect(screen.getByText('Create your first dossier.')).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);
  });

  it('retains a report delete failure reason',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'report delete failed'}),
      {status:503,statusText:'Service Unavailable',headers:{'Content-Type':'application/json'}})));
    await expect(deleteReport('r-existing')).rejects.toThrow('API error: 503 Service Unavailable: report delete failed');
  });

  it.each([
    ['proxy HTML','<html>upstream failed</html>','text/html'],
    ['malformed JSON','{broken','application/json'],
    ['validation object',JSON.stringify({detail:[{loc:['body','title'],msg:'invalid'}]}),'application/json'],
    ['empty detail',JSON.stringify({detail:'  '}),'application/json'],
  ])('keeps the HTTP fallback for %s',async(_name,body,contentType)=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(body,
      {status:503,statusText:'Service Unavailable',headers:{'Content-Type':contentType}})));
    await expect(createReport({})).rejects.toThrow(/^API error: 503 Service Unavailable$/);
  });
});
