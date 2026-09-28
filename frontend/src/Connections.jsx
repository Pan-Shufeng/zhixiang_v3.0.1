import React,{useEffect,useState} from 'react';
import {ArrowUpRight,Check,Copy,Link,LoaderCircle,RefreshCw,Unplug} from 'lucide-react';
import './connections.css';

const labels={codex:'Codex',workbuddy:'WorkBuddy',dsh:'DSH'};
const trial='请使用知向工具列出我保存的问题，并获取知向网页入口；如果你有内置浏览器，请打开这个入口。暂时不要修改或保存判断。';
async function request(path,body){const r=await fetch('/api/connections'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw Error(data.error||'这一步没有完成');return data}

export default function Connections(){
 const [data,setData]=useState(null),[busy,setBusy]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState(''),[dsh,setDsh]=useState(''),[dshUrl,setDshUrl]=useState('');
 async function refresh(){try{setData(await request(''));setError('')}catch(e){setError(e.message)}}
 useEffect(()=>{refresh()},[]);
 async function action(kind,client){setBusy(client);setMessage('');setError('');try{const value=await request('/'+kind,{client});if(value.command)setDsh(value.command);if(value.url)setDshUrl(value.url);setMessage(value.message||'连接命令已生成，请在平时使用 DSH 的终端运行。');await refresh()}catch(e){setError(e.message)}finally{setBusy('')}}
 async function copy(value){try{await navigator.clipboard.writeText(value);setMessage('已复制。')}catch{setError('浏览器未允许复制，请选中文字后复制。')}}
 return <div className="connections-page"><div className="eyebrow">把知向带到你熟悉的地方</div><h1>连接我的 AI 客户端</h1><p className="connections-intro">继续在熟悉的对话里找依据、读资料、更新判断。<br/>想看完整页面时，让 AI 在内置浏览器打开知向就好。</p>
 <div className="connection-summary"><Link size={20}/><div><strong>同一份资料，两种使用方式</strong><span>AI 调用工具处理资料；知向网页展示来源和判断。连接配置不包含 API Key。</span></div><button className="secondary compact" onClick={refresh}><RefreshCw size={14}/>刷新状态</button></div>
 {error&&<div className="modal-error" role="alert">{error}</div>}{message&&<div className="connection-message" role="status"><Check size={16}/>{message}</div>}
 {!data&&<p><LoaderCircle className="spin" size={18}/> 正在读取连接设置…</p>}
 <div className="connection-grid">{data?.clients.map(client=>{const event=data.events?.[client.id];const installed=client.state==='configured';return <section className="connection-card" key={client.id}><div className="connection-card-head"><h2>{labels[client.id]}</h2><span className={'connection-badge '+(installed?'ready':'')}>{installed?'配置已加入':client.state==='conflict'?'已连接其他知向':client.state==='unreadable'?'配置需检查':client.state==='available'?'找到已有 DSH':client.id==='dsh'?'需要指定启动方式':'等待连接'}</span></div><p>{client.id==='dsh'?'使用你已有的 DSH 和原来的配置。本入口启动时加载知向，之后也从这里启动。':'加入知向工具，保留其他服务与设置。客户端需要重新加载连接或新开对话。'}</p>
 <div className="connection-actions">{client.id==='dsh'?<><button className="primary" disabled={!!busy||client.state!=='available'} onClick={()=>action('dsh-launch','dsh')}>用已有 DSH 打开<ArrowUpRight size={15}/></button><button className="secondary compact" disabled={!!busy} onClick={()=>action('dsh-patch','dsh')}>生成连接命令</button></>:<><button className="primary" disabled={!!busy||installed||['conflict','unreadable'].includes(client.state)} onClick={()=>action('install',client.id)}>{busy===client.id?<LoaderCircle className="spin" size={15}/>:<Link size={15}/>} {installed?'配置已加入':'一键加入连接'}</button>{installed&&<button className="secondary compact" disabled={!!busy} onClick={()=>action('remove',client.id)}><Unplug size={14}/>移除连接</button>}</>}</div>
 <div className="connection-evidence">{event?.last_tool_at?<><Check size={14}/><span>最近成功调用：{new Date(event.last_tool_at).toLocaleString('zh-CN')}<small>历史记录，不代表客户端此刻仍在线。</small></span></>:event?<span>客户端已完成握手；还没有成功调用工具的记录。</span>:<span>尚未收到客户端的真实工具调用。配置完成后，请发送下方试用语句。</span>}</div>
 {client.id!=='dsh'&&<details><summary>配置位置与手动连接</summary><p className="connection-path">{client.path}</p><p>自动添加前会在原配置旁保存备份。手动添加时仅合并 zhixiang 项，不要覆盖其他配置。</p><pre>{data.manual[client.id]}</pre><button className="secondary compact" onClick={()=>copy(data.manual[client.id])}><Copy size={14}/>复制配置</button></details>}
 {client.id==='dsh'&&<><small>支持具有 web 与 --patch 入口、可加载官方 MCP 客户端的 DSH。未找到时可在原 DSH 终端运行生成的命令；不会替你重装 DSH。</small>{dsh&&<div className="connection-command"><pre>{dsh}</pre><button className="secondary compact" onClick={()=>copy(dsh)}><Copy size={14}/>复制命令</button></div>}{dshUrl&&<a href={dshUrl} target="_blank" rel="noreferrer">打开 DSH 对话页面 ↗</a>}</>}
 </section>})}</div>
 <section className="connection-try"><div><div className="eyebrow">连接后，试着说一句</div><p>{trial}</p></div><button className="secondary" onClick={()=>copy(trial)}><Copy size={16}/>复制试用语句</button></section>
 <p className="connection-footnote">知向网页地址：<a href={data?.web_url||'/'} target="_blank" rel="noreferrer">{data?.web_url||location.origin}</a>。支持本机 Windows 客户端；云端客户端不能直接访问你电脑的本地服务。移动解压文件夹后，需要重新设置连接。</p>
 </div>
}
