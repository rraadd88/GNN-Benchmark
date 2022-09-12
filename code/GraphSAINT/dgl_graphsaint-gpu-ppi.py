import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import dgl
# import time
from ogb.nodeproppred import DglNodePropPredDataset
from load_graph import load_reddit, load_ogb, inductive_split, load_ppi, load_flickr, load_yelp
from sklearn.metrics import f1_score
from codecarbon import EmissionsTracker
from energy_logger import energy_logger


class GraphSAINT(nn.Module):
    def __init__(self, in_feats, n_hidden, n_classes):
        super().__init__()
        self.layers = nn.ModuleList()
        self.layers.append(dgl.nn.SAGEConv(in_feats, n_hidden, 'mean'))
        # self.layers.append(dgl.nn.SAGEConv(n_hidden, n_hidden, 'mean'))
        self.layers.append(dgl.nn.SAGEConv(n_hidden, n_classes, 'mean'))
        self.dropout = nn.Dropout(0.0)
        self.n_hidden = n_hidden
        self.n_classes = n_classes

    def forward(self, sg, x):
        h = x
        for l, layer in enumerate(self.layers):
            h = layer(sg, h)
            if l != len(self.layers) - 1:
                h = F.relu(h)
                h = self.dropout(h)
        # return h
        return F.log_softmax(h, dim=-1)

    def inference(self, g, device, batch_size, num_workers, buffer_device=None):
        feat = g.ndata['feat']
        sampler = dgl.dataloading.MultiLayerFullNeighborSampler(1)
        dataloader = dgl.dataloading.DataLoader(
                g, torch.arange(g.num_nodes()).to(g.device), sampler, device=device,
                batch_size=batch_size, shuffle=False, drop_last=False,
                num_workers=num_workers)

        if buffer_device is None:
            buffer_device = device

        for l, layer in enumerate(self.layers):
            y = torch.empty(
                g.num_nodes(), self.n_hidden if l != len(self.layers) - 1 else self.n_classes,
                device=buffer_device, pin_memory=True)
            feat = feat.to(device)
            for _, (input_nodes, output_nodes, blocks) in enumerate(dataloader):
                x = feat[input_nodes]
                h = layer(blocks[0], x)
                if l != len(self.layers) - 1:
                    h = F.relu(h)
                    h = self.dropout(h)
                y[output_nodes[0]:output_nodes[-1]+1] = h.to(buffer_device)
            feat = y
        return y


def train():
    model.train()
    for sg in dataloader:
        
        sg = sg.to('cuda')
        x = sg.ndata['feat']
        y = sg.ndata['label']
        m = sg.ndata['train_mask'].bool()
        
        y_hat = model(sg, x)
        # loss = F.cross_entropy(y_hat[m], y[m])
        loss_fc = nn.BCEWithLogitsLoss()
        loss = loss_fc(y_hat[m], y[m].float())
        opt.zero_grad()
        loss.backward()
        opt.step()


@torch.no_grad()
def test():
    model.eval()

    m_train = graph.ndata['train_mask'].bool()
    m_val = graph.ndata['val_mask'].bool()
    m_test = graph.ndata['test_mask'].bool()
    y_hat = model.inference(graph, device, 512, 0, 'cpu')

    train_preds = y_hat[m_train]
    train_labels = graph.ndata['label'][m_train]

    val_preds = y_hat[m_val]
    val_labels = graph.ndata['label'][m_val]

    test_preds = y_hat[m_test]
    test_labels = graph.ndata['label'][m_test]

    train_preds[train_preds > 0] = 1
    train_preds[train_preds <= 0] = 0
    val_preds[val_preds > 0] = 1
    val_preds[val_preds <= 0] = 0
    test_preds[test_preds > 0] = 1
    test_preds[test_preds <= 0] = 0
    train_acc = f1_score(train_preds.cpu(), train_labels.cpu(), average='micro')
    val_acc = f1_score(val_preds.cpu(), val_labels.cpu(), average='micro')
    test_acc = f1_score(test_preds.cpu(), test_labels.cpu(), average='micro')
    print('Training acc:', train_acc.item(),  'Validation acc:', val_acc.item(), 'Testing acc:', test_acc.item())


log_name = 'dgl_graphsaint-ppi-cpugpu'
tracker = EmissionsTracker(measure_power_secs=0.1, project_name=log_name, output_dir='log/', output_file='GraphSAINT-emissions.csv',)
energy_logger(log_name)
tracker.start()

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

path = os.path.abspath(os.path.join(os.getcwd(), "../dataset/"))

graph, num_classes = load_ppi()

# n_nodes = graph.num_nodes()
# n_edges = graph.num_edges()
# print(n_nodes)
# print(n_edges)

iter = (torch.count_nonzero(graph.ndata['train_mask'])/(3000*3)).int()
# print(iter)

model = GraphSAINT(graph.ndata['feat'].shape[1], 256, num_classes).to('cuda')
opt = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=0)

sampler = dgl.dataloading.SAINTSampler(mode='walk', budget=[3000, 2], cache=False)
        # prefetch_ndata=['feat', 'label', 'train_mask', 'val_mask', 'test_mask'])

dataloader = dgl.dataloading.DataLoader(graph, torch.arange(iter), sampler, batch_size=1, num_workers=0, device='cpu', shuffle=True,
                                        drop_last=False, use_uva=False)


print('DGL, ppi, GraphSAINT, cuda')
for epoch in range(100):
    train()
print('Training done!')
# test()
# print('===============================')
tracker.stop()
