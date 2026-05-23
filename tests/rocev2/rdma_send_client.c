#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include <rdma/rdma_cma.h>

int main(int argc, char **argv) {
    if (argc != 2) {
        printf("Usage: %s <server_ip>\n", argv[0]);
        return 1;
    }
    struct rdma_cm_id *id = NULL;
    struct ibv_qp_init_attr qp_attr;
    struct ibv_pd *pd;
    struct ibv_cq *cq;
    struct ibv_mr *mr;
    char buf[64] = "Hello RDMA";
    int ret;

    // 1. Create CM ID
    ret = rdma_create_id(NULL, &id, NULL, RDMA_PS_TCP);
    if (ret) { perror("rdma_create_id"); return 1; }

    // 2. Convert server IP to sockaddr_in
    struct sockaddr_in server_addr;
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(7474);               // Fixed port, server also listens on this port
    inet_pton(AF_INET, argv[1], &server_addr.sin_addr);

    // 3. Resolve address
    ret = rdma_resolve_addr(id, NULL, (struct sockaddr *)&server_addr, 2000);
    if (ret) { perror("rdma_resolve_addr"); return 1; }

    // 4. Resolve route
    ret = rdma_resolve_route(id, 2000);
    if (ret) { perror("rdma_resolve_route"); return 1; }

    // 5. Allocate PD
    pd = ibv_alloc_pd(id->verbs);
    if (!pd) { perror("ibv_alloc_pd"); return 1; }

    // 6. Create CQ
    cq = ibv_create_cq(id->verbs, 10, NULL, NULL, 0);
    if (!cq) { perror("ibv_create_cq"); return 1; }

    // 7. Configure QP
    memset(&qp_attr, 0, sizeof(qp_attr));
    qp_attr.cap.max_send_wr = 1;
    qp_attr.cap.max_recv_wr = 1;
    qp_attr.cap.max_send_sge = 1;
    qp_attr.cap.max_recv_sge = 1;
    qp_attr.qp_type = IBV_QPT_RC;
    qp_attr.send_cq = cq;
    qp_attr.recv_cq = cq;

    // 8. Create QP
    ret = rdma_create_qp(id, pd, &qp_attr);
    if (ret) { perror("rdma_create_qp"); return 1; }

    // 9. Register MR
    mr = ibv_reg_mr(pd, buf, sizeof(buf), IBV_ACCESS_LOCAL_WRITE);
    if (!mr) { perror("ibv_reg_mr"); return 1; }

    // 10. Establish connection
    ret = rdma_connect(id, NULL);
    if (ret) { perror("rdma_connect"); return 1; }
    printf("Connection established, sending data...\n");

    // 11. Post send request
    struct ibv_sge sge = {.addr = (uintptr_t)buf, .length = strlen(buf)+1, .lkey = mr->lkey};
    struct ibv_send_wr send_wr = {.wr_id = 0, .sg_list = &sge, .num_sge = 1, .opcode = IBV_WR_SEND, .send_flags = IBV_SEND_SIGNALED};
    struct ibv_send_wr *bad_send_wr;
    ret = ibv_post_send(id->qp, &send_wr, &bad_send_wr);
    if (ret) { perror("ibv_post_send"); return 1; }

    // 12. Poll CQ for send completion
    struct ibv_wc wc;
    int poll_count = 0;
    while (poll_count == 0) {
        poll_count = ibv_poll_cq(cq, 1, &wc);
    }
    if (wc.status == IBV_WC_SUCCESS) {
        printf("Data sent successfully\n");
    } else {
        printf("Send failed\n");
    }

    return 0;
}
