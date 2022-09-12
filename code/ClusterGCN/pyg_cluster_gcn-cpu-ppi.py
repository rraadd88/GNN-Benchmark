import os
import torch
import torch.nn.functional as F
from create_pyg import PPI
from torch_geometric.loader import ClusterData, ClusterLoader, NeighborSampler
from torch_geometric.nn import SAGEConv
from sklearn.metrics import f1_score
from codecarbon import EmissionsTracker
from energy_logger import energy_logger


class ClusterGCN(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels):
        super().__init__()
        self.convs = torch.nn.ModuleList()
        self.convs.append(SAGEConv(in_channels, hidden_channels, aggr='mean'))
        self.convs.append(SAGEConv(hidden_channels, out_channels, aggr='mean'))
        self.dropout = torch.nn.Dropout(p=0.0)

    def forward(self, x, edge_index):
        for i, conv in enumerate(self.convs):
            x = conv(x, edge_index)
            if i != len(self.convs) - 1:
                x = F.relu(x)
                x = F.dropout(x, p=0.0, training=self.training)
        return F.log_softmax(x, dim=-1)

    def inference(self, x_all):
        for i, conv in enumerate(self.convs):
            xs = []
            for batch_size, n_id, adj in subgraph_loader:
                edge_index, _, size = adj.to(device)
                x = x_all[n_id].to(device)
                x_target = x[:size[1]]
                x = conv((x, x_target), edge_index)
                if i != len(self.convs) - 1:
                    x = F.relu(x)
                    x = self.dropout(x)
                xs.append(x.cpu())

            x_all = torch.cat(xs, dim=0)

        return x_all

def train():
    model.train()

    for batch in train_loader:
        batch = batch.to(device)
        optimizer.zero_grad()
        out = model(batch.x, batch.edge_index)
        # loss = F.nll_loss(out[batch.train_mask], batch.y[batch.train_mask])
        # loss_fcn = torch.nn.MultiLabelSoftMarginLoss()
        loss_fcn = torch.nn.BCEWithLogitsLoss()
        loss = loss_fcn(out[batch.train_mask], batch.y[batch.train_mask].float())
        # loss = F.cross_entropy(out[batch.train_mask], batch.y[batch.train_mask])
        loss.backward()
        optimizer.step()


@torch.no_grad()
def test():
    model.eval()

    out = model.inference(data.x)
    y_pred = out
    y_pred[y_pred > 0] = 1
    y_pred[y_pred <= 0] = 0

    accs = []
    for mask in [data.train_mask, data.val_mask, data.test_mask]:
        f1_micro = f1_score(data.y[mask], y_pred[mask], average='micro')
        accs.append(f1_micro)  
        
    print('Training acc:', accs[0],  'Validation acc:', accs[1], 'Testing acc:', accs[2])


log_name = 'pyg_cluster-ppi-cpu'
tracker = EmissionsTracker(measure_power_secs=0.1, project_name=log_name, output_dir='log/', output_file='ClusterGCN-emissions.csv',)
energy_logger(log_name)
tracker.start()

device = torch.device('cpu')

path = os.path.abspath(os.path.join(os.getcwd(), "../dataset/ppi/"))

dataset = PPI(path)
data = dataset[0]

cluster_data = ClusterData(data, num_parts=2000, recursive=False, save_dir='cache/')
train_loader = ClusterLoader(cluster_data, batch_size=50, shuffle=True, num_workers=0)

subgraph_loader = NeighborSampler(data.edge_index, sizes=[-1], batch_size=1024, shuffle=False, num_workers=0)

model = ClusterGCN(dataset.num_features, 256, dataset.num_classes).to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

print('PyG, ppi, ClusterGCN, cpu')
for epoch in range(10):
    train()
print('Training done!')
# test()
# print('===============================')
tracker.stop()